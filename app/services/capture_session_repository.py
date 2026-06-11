"""Cross-device capture sessions — Supabase Postgres + Storage."""

from __future__ import annotations

import asyncio
import io
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

import structlog

from app.config import Settings
from app.markets.registry import SUPPORTED_REGIONS, resolve_market
from app.models.capture_session import SessionDetailResponse, SessionImageItem
from app.models.responses import UnifiedViewMethod
from app.utils.uploads import UploadTuple

if TYPE_CHECKING:
    from app.services.analyzer import AssetAnalysisService

logger = structlog.get_logger()

_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{20,128}$")


def is_valid_session_token(token: str) -> bool:
    return bool(token and _TOKEN_RE.match(token.strip()))


def resolve_session_market_region(
    row: dict,
    client_region: str | None = None,
    *,
    default_region: str = "IN",
) -> str:
    """Prefer market region stored on the session (laptop QR origin)."""
    stored = (row.get("market_region") or "").strip().upper()
    if stored in SUPPORTED_REGIONS:
        return stored
    client = (client_region or "").strip().upper()
    if client in SUPPORTED_REGIONS:
        return client
    fallback = (default_region or "IN").strip().upper()
    return fallback if fallback in SUPPORTED_REGIONS else "IN"


class CaptureSessionRepository:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client: Any = None

    @property
    def enabled(self) -> bool:
        return (
            self.settings.capture_session_enabled
            and self.settings.supabase_persist_enabled
            and bool(self.settings.supabase_url.strip())
            and bool(self.settings.supabase_service_role_key.strip())
        )

    def _get_client(self) -> Any:
        if self._client is None:
            from supabase import create_client

            self._client = create_client(
                self.settings.supabase_url.strip(),
                self.settings.supabase_service_role_key.strip(),
            )
        return self._client

    def _bucket(self) -> str:
        return self.settings.capture_storage_bucket.strip() or "capture-images"

    def _storage_prefix(self, user_id: int, session_id: str) -> str:
        return f"user_{user_id}/sessions/{session_id}"

    def _upload_path(self, user_id: int, session_id: str, sort_order: int) -> str:
        # Unique suffix prevents path collisions/overwrites when images are
        # deleted and re-added (sort_order alone is reused after renumbering).
        suffix = secrets.token_hex(4)
        return (
            f"{self._storage_prefix(user_id, session_id)}/"
            f"upload_{sort_order:02d}_{suffix}.jpg"
        )

    def _signed_url(self, storage_path: str) -> str | None:
        try:
            result = (
                self._get_client()
                .storage.from_(self._bucket())
                .create_signed_url(storage_path, self.settings.supabase_signed_url_ttl_seconds)
            )
            if isinstance(result, dict):
                return result.get("signedURL") or result.get("signedUrl")
            return None
        except Exception as exc:
            logger.warning("session_signed_url_failed", path=storage_path, error=str(exc))
            return None

    def _parse_ts(self, value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None

    def _iso(self, value: Any) -> str:
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc).isoformat()
        return str(value or "")

    def _expire_if_needed(self, row: dict) -> dict:
        expires = self._parse_ts(row.get("expires_at"))
        if (
            expires
            and expires < datetime.now(timezone.utc)
            and row.get("status") == "active"
        ):
            client = self._get_client()
            client.table("capture_sessions").update({"status": "expired"}).eq(
                "id", row["id"]
            ).execute()
            row["status"] = "expired"
        return row

    def _recover_stale_analyzing_sync(self, row: dict) -> dict:
        if row.get("status") != "analyzing" or row.get("entry_id"):
            return row
        updated = self._parse_ts(row.get("updated_at"))
        if not updated:
            return row
        stale_after = timedelta(seconds=self.settings.capture_session_analyze_stale_seconds)
        if datetime.now(timezone.utc) - updated <= stale_after:
            return row
        logger.warning("session_analyze_stale_unlock", session_id=row.get("id"))
        self._unlock_session_sync(row["id"])
        row["status"] = "active"
        return row

    def _fetch_images(self, session_id: str) -> list[dict]:
        result = (
            self._get_client()
            .table("capture_session_images")
            .select("*")
            .eq("session_id", session_id)
            .order("sort_order")
            .execute()
        )
        return result.data or []

    def _to_image_items(self, images: list[dict]) -> list[SessionImageItem]:
        items: list[SessionImageItem] = []
        for img in images:
            items.append(
                SessionImageItem(
                    id=img["id"],
                    sort_order=img["sort_order"],
                    preview_url=self._signed_url(img["storage_path"]),
                    source=img.get("source") or "mobile",
                    file_name=img.get("file_name"),
                    mime_type=img.get("mime_type") or "image/jpeg",
                    byte_size=img.get("byte_size"),
                )
            )
        return items

    def _session_total_bytes(self, images: list[dict]) -> int:
        return sum(img.get("byte_size") or 0 for img in images)

    def _to_detail(self, row: dict, images: list[dict]) -> SessionDetailResponse:
        return SessionDetailResponse(
            session_token=row["session_token"],
            status=row["status"],
            processing_mode=row.get("processing_mode") or "direct",
            market_region=resolve_session_market_region(
                row, default_region=self.settings.market_region
            ),
            image_count=row.get("image_count") or len(images),
            max_images=self.settings.max_images,
            total_bytes=self._session_total_bytes(images),
            entry_id=row.get("entry_id"),
            expires_at=self._iso(row.get("expires_at")),
            images=self._to_image_items(images),
        )

    def _get_row_by_token_sync(self, token: str) -> dict | None:
        result = (
            self._get_client()
            .table("capture_sessions")
            .select("*")
            .eq("session_token", token)
            .limit(1)
            .execute()
        )
        if not result.data:
            return None
        row = self._expire_if_needed(result.data[0])
        return self._recover_stale_analyzing_sync(row)

    def _create_sync(
        self,
        *,
        user_id: int,
        processing_mode: str,
        market_region: str = "IN",
    ) -> SessionDetailResponse:
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(
            hours=self.settings.capture_session_ttl_hours
        )
        region = resolve_market(market_region, self.settings).region
        row = {
            "session_token": token,
            "user_id": user_id,
            "status": "active",
            "processing_mode": processing_mode,
            "market_region": region,
            "image_count": 0,
            "expires_at": expires_at.isoformat(),
        }
        inserted = self._get_client().table("capture_sessions").insert(row).execute()
        session = inserted.data[0]
        return self._to_detail(session, [])

    def _upload_sync(
        self,
        *,
        token: str,
        user_id: int,
        raw: bytes,
        filename: str,
        mime_type: str,
        source: str,
    ) -> SessionDetailResponse:
        row = self._get_row_by_token_sync(token)
        if not row:
            raise ValueError("Session not found")
        if row.get("user_id") != user_id:
            raise ValueError("Session not found")
        if row["status"] != "active":
            raise ValueError(f"Session is {row['status']}; cannot add images")

        count = row.get("image_count") or 0
        if count >= self.settings.max_images:
            raise ValueError(f"Maximum {self.settings.max_images} images per session")

        existing_images = self._fetch_images(row["id"])
        existing_total = self._session_total_bytes(existing_images)
        new_total = existing_total + len(raw)
        if new_total > self.settings.max_session_upload_total_bytes:
            limit_mb = self.settings.max_session_upload_total_mb
            raise ValueError(
                f"Session upload total would exceed {limit_mb}MB limit "
                f"({round(new_total / 1024 / 1024, 1)}MB)"
            )

        sort_order = count + 1
        path = self._upload_path(user_id, row["id"], sort_order)
        storage = self._get_client().storage.from_(self._bucket())
        storage.upload(
            path,
            raw,
            {"content-type": mime_type, "upsert": "true"},
        )

        img_row = {
            "session_id": row["id"],
            "user_id": user_id,
            "sort_order": sort_order,
            "storage_path": path,
            "source": source,
            "file_name": filename,
            "mime_type": mime_type,
            "byte_size": len(raw),
        }
        self._get_client().table("capture_session_images").insert(img_row).execute()
        new_count = sort_order
        self._get_client().table("capture_sessions").update(
            {"image_count": new_count}
        ).eq("id", row["id"]).execute()

        row["image_count"] = new_count
        images = self._fetch_images(row["id"])
        return self._to_detail(row, images)

    def _delete_image_sync(
        self,
        *,
        token: str,
        user_id: int,
        image_id: str,
    ) -> SessionDetailResponse:
        row = self._get_row_by_token_sync(token)
        if not row:
            raise ValueError("Session not found")
        if row.get("user_id") != user_id:
            raise ValueError("Session not found")
        if row["status"] != "active":
            raise ValueError(f"Session is {row['status']}; cannot delete images")

        images = self._fetch_images(row["id"])
        target = next((i for i in images if i["id"] == image_id), None)
        if not target:
            raise ValueError("Image not found")

        storage = self._get_client().storage.from_(self._bucket())
        try:
            storage.remove([target["storage_path"]])
        except Exception as exc:
            logger.warning("session_storage_remove_failed", error=str(exc))

        client = self._get_client()
        client.table("capture_session_images").delete().eq("id", image_id).execute()

        remaining = [i for i in images if i["id"] != image_id]
        for idx, img in enumerate(remaining, start=1):
            if img["sort_order"] != idx:
                client.table("capture_session_images").update({"sort_order": idx}).eq(
                    "id", img["id"]
                ).execute()

        new_count = len(remaining)
        client.table("capture_sessions").update({"image_count": new_count}).eq(
            "id", row["id"]
        ).execute()
        row["image_count"] = new_count
        refreshed = self._fetch_images(row["id"])
        return self._to_detail(row, refreshed)

    def _download_image_bytes(self, storage_path: str) -> bytes:
        data = self._get_client().storage.from_(self._bucket()).download(storage_path)
        if isinstance(data, bytes):
            return data
        if hasattr(data, "read"):
            return data.read()
        return bytes(data)

    def _try_lock_analyzing_sync(self, token: str, user_id: int) -> tuple[dict | None, bool]:
        """Return (session row, lock_acquired). lock_acquired is True only when this call set analyzing."""
        row = self._get_row_by_token_sync(token)
        if not row or row.get("user_id") != user_id:
            return None, False
        if row["status"] == "analyzing":
            return row, False
        if row["status"] == "completed":
            return row, False
        if row["status"] != "active":
            return None, False
        if (row.get("image_count") or 0) < self.settings.min_images:
            return None, False

        updated = (
            self._get_client()
            .table("capture_sessions")
            .update({"status": "analyzing"})
            .eq("id", row["id"])
            .eq("status", "active")
            .execute()
        )
        if updated.data:
            return updated.data[0], True
        refetched = self._get_row_by_token_sync(token)
        if refetched and refetched["status"] == "analyzing":
            return refetched, False
        return refetched, False

    def _complete_session_sync(
        self,
        *,
        session_id: str,
        entry_id: str,
    ) -> None:
        self._get_client().table("capture_sessions").update(
            {"status": "completed", "entry_id": entry_id}
        ).eq("id", session_id).execute()

    def _unlock_session_sync(self, session_id: str) -> None:
        self._get_client().table("capture_sessions").update({"status": "active"}).eq(
            "id", session_id
        ).eq("status", "analyzing").execute()

    def _cancel_analysis_sync(
        self,
        *,
        token: str,
        user_id: int,
        clear_images: bool = False,
    ) -> SessionDetailResponse:
        row = self._get_row_by_token_sync(token)
        if not row or row.get("user_id") != user_id:
            raise ValueError("Session not found")
        if row["status"] == "completed":
            raise ValueError("Session already completed")
        if row["status"] == "expired":
            raise ValueError("Session has expired")
        if row["status"] == "analyzing":
            self._unlock_session_sync(row["id"])
            row["status"] = "active"
        elif row["status"] != "active":
            raise ValueError(f"Session is {row['status']}")

        if clear_images:
            while True:
                images = self._fetch_images(row["id"])
                if not images:
                    row["image_count"] = 0
                    break
                self._delete_image_sync(
                    token=token,
                    user_id=user_id,
                    image_id=images[0]["id"],
                )
            row = self._get_row_by_token_sync(token) or row

        images = self._fetch_images(row["id"])
        return self._to_detail(row, images)

    async def create_session(
        self,
        *,
        user_id: int,
        processing_mode: str,
        market_region: str = "IN",
    ) -> SessionDetailResponse:
        return await asyncio.to_thread(
            self._create_sync,
            user_id=user_id,
            processing_mode=processing_mode,
            market_region=market_region,
        )

    async def get_session(self, *, token: str, user_id: int) -> SessionDetailResponse | None:
        def _get() -> SessionDetailResponse | None:
            row = self._get_row_by_token_sync(token)
            if not row or row.get("user_id") != user_id:
                return None
            images = self._fetch_images(row["id"])
            return self._to_detail(row, images)

        return await asyncio.to_thread(_get)

    async def upload_image(
        self,
        *,
        token: str,
        user_id: int,
        raw: bytes,
        filename: str,
        mime_type: str,
        source: str,
    ) -> SessionDetailResponse:
        return await asyncio.to_thread(
            self._upload_sync,
            token=token,
            user_id=user_id,
            raw=raw,
            filename=filename,
            mime_type=mime_type,
            source=source,
        )

    async def delete_image(
        self,
        *,
        token: str,
        user_id: int,
        image_id: str,
    ) -> SessionDetailResponse:
        return await asyncio.to_thread(
            self._delete_image_sync,
            token=token,
            user_id=user_id,
            image_id=image_id,
        )

    async def cancel_analysis(
        self,
        *,
        token: str,
        user_id: int,
        clear_images: bool = False,
    ) -> SessionDetailResponse:
        return await asyncio.to_thread(
            self._cancel_analysis_sync,
            token=token,
            user_id=user_id,
            clear_images=clear_images,
        )

    async def analyze_session(
        self,
        *,
        token: str,
        user_id: int,
        analyzer: AssetAnalysisService,
        locale: str | None = None,
        market_region: str | None = None,
    ) -> tuple[SessionDetailResponse | None, str | None]:
        """Returns (detail, error_message). Runs analyzer when lock acquired."""

        row, lock_acquired = await asyncio.to_thread(
            self._try_lock_analyzing_sync, token, user_id
        )
        if not row:
            return None, "Session not found"
        if row["status"] == "completed" and row.get("entry_id"):
            images = await asyncio.to_thread(self._fetch_images, row["id"])
            return self._to_detail(row, images), None
        if (
            not lock_acquired
            and row["status"] == "analyzing"
            and not row.get("entry_id")
        ):
            # Another request holds the lock — caller polls
            images = await asyncio.to_thread(self._fetch_images, row["id"])
            return self._to_detail(row, images), None
        if row["status"] != "analyzing":
            return None, "Session cannot be analyzed in its current state"

        images = await asyncio.to_thread(self._fetch_images, row["id"])
        if len(images) < self.settings.min_images:
            await asyncio.to_thread(self._unlock_session_sync, row["id"])
            return None, f"At least {self.settings.min_images} image required"

        effective_region = resolve_session_market_region(
            row,
            market_region,
            default_region=self.settings.market_region,
        )
        market = resolve_market(effective_region, self.settings)
        effective_locale = locale or market.default_locale

        try:
            files: list[UploadTuple] = []
            for img in images:
                raw = await asyncio.to_thread(
                    self._download_image_bytes, img["storage_path"]
                )
                name = img.get("file_name") or f"upload_{img['sort_order']}.jpg"
                files.append((io.BytesIO(raw), name, raw))

            mode = row.get("processing_mode") or "direct"
            method = (
                UnifiedViewMethod.COLLAGE
                if mode == "collage"
                else UnifiedViewMethod.MULTI_IMAGE
            )
            api_route = (
                "/v1/assets/analyze/collage"
                if mode == "collage"
                else "/v1/assets/analyze/multi"
            )

            response = await analyzer.analyze(
                files=files,
                method=method,
                locale=effective_locale,
                market_region=effective_region,
                processing_mode=mode,
                api_route=api_route,
            )
            entry_id = response.entry_id or response.request_id
            await asyncio.to_thread(
                self._complete_session_sync,
                session_id=row["id"],
                entry_id=entry_id,
            )
            row["status"] = "completed"
            row["entry_id"] = entry_id
            return self._to_detail(row, images), None
        except Exception as exc:
            logger.error("session_analyze_failed", token_prefix=token[:8], error=str(exc))
            await asyncio.to_thread(self._unlock_session_sync, row["id"])
            row["status"] = "active"
            return (
                self._to_detail(row, images),
                "Analysis failed — please try again.",
            )


_repository: CaptureSessionRepository | None = None


def get_capture_session_repository(settings: Settings) -> CaptureSessionRepository:
    global _repository
    if _repository is None or _repository.settings is not settings:
        _repository = CaptureSessionRepository(settings)
    return _repository
