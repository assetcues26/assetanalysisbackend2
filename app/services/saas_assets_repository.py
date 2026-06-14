"""SaaS asset register — Supabase schema `saas` + Storage."""

from __future__ import annotations

import asyncio
import csv
import io
import re
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import structlog

from app.config import Settings
from app.models.saas_assets import (
    AssetCreateSessionDetail,
    CompleteAssetSessionResponse,
    CreateAssetResponse,
    SaasAnalysisItem,
    SaasAssetDetailResponse,
    SaasAssetSummary,
)
from app.services.tagging_ai_client import (
    analyze_asset_with_tagging_ai,
    compute_ai_status,
    extract_summary_fields,
)

logger = structlog.get_logger()

_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{20,128}$")

ASSET_METADATA_KEYS = (
    "assetid",
    "assetname",
    "description",
    "tagnumber",
    "assetnumber",
    "assetclassid",
    "assetclassname",
    "categoryid",
    "categoryname",
    "subcategoryid",
    "subcategoryname",
    "makemodelid",
    "makemodelname",
    "companyid",
    "company",
    "customerid",
    "assettaggingdetailid",
    "cost",
    "acquisitiondate",
)

REQUIRED_CREATE_KEYS = (
    "assetname",
    "tagnumber",
    "assetnumber",
    "makemodelid",
    "makemodelname",
    "companyid",
    "company",
    "customerid",
    "cost",
    "acquisitiondate",
    "assetclassname",
)


def is_valid_asset_session_token(token: str) -> bool:
    return bool(token and _TOKEN_RE.match(token.strip()))


def validate_create_metadata(data: dict[str, Any], *, require_asset_image: bool = True) -> None:
    missing = [k for k in REQUIRED_CREATE_KEYS if not str(data.get(k) or "").strip()]
    if missing:
        raise ValueError(f"Missing required fields: {', '.join(missing)}")
    date_val = str(data.get("acquisitiondate") or "").strip()
    if not re.match(r"^\d{2}-\d{2}-\d{4}$", date_val):
        raise ValueError("acquisitiondate must be DD-MM-YYYY")
    if require_asset_image and not data.get("_has_asset_image"):
        raise ValueError("assetimage is required")


class SaasAssetsRepository:
    TABLE_MAP = {
        "registered_assets": "saas_registered_assets",
        "asset_analyses": "saas_asset_analyses",
        "asset_create_sessions": "saas_asset_create_sessions",
        "web_drafts": "saas_web_drafts",
        "activity_events": "saas_activity_events",
    }

    SORTABLE_FIELDS = frozenset(
        {"assetname", "acquisitiondate", "cost", "ai_status", "company", "created_at", "assetid"}
    )

    def __init__(self, settings: Settings):
        self.settings = settings
        self._client: Any = None

    @property
    def enabled(self) -> bool:
        return (
            self.settings.saas_assets_enabled
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

    def _table(self, name: str) -> Any:
        table_name = self.TABLE_MAP.get(name, name)
        return self._get_client().table(table_name)

    def _bucket(self) -> str:
        return self.settings.saas_assets_storage_bucket.strip() or "saas-asset-images"

    def _storage_prefix(self, user_id: int, asset_id: str) -> str:
        return f"user_{user_id}/saas_assets/{asset_id}"

    def _asset_image_path(self, user_id: int, asset_id: str, kind: str) -> str:
        return f"{self._storage_prefix(user_id, asset_id)}/{kind}.jpg"

    def _session_image_path(self, user_id: int, session_id: str, kind: str) -> str:
        suffix = secrets.token_hex(4)
        return f"user_{user_id}/saas_sessions/{session_id}/{kind}_{suffix}.jpg"

    def _signed_url(self, storage_path: str | None) -> str | None:
        if not storage_path:
            return None
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
            logger.warning("saas_signed_url_failed", path=storage_path, error=str(exc))
            return None

    def _upload_bytes(self, path: str, data: bytes, mime_type: str = "image/jpeg") -> None:
        storage = self._get_client().storage.from_(self._bucket())
        storage.upload(path, data, {"content-type": mime_type, "upsert": "true"})

    def _download_bytes(self, path: str) -> bytes:
        return self._get_client().storage.from_(self._bucket()).download(path)

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

    def _normalize_cost(self, value: Any) -> float | None:
        if value is None or value == "":
            return None
        return float(Decimal(str(value)))

    def _row_to_metadata(self, row: dict) -> dict[str, Any]:
        meta: dict[str, Any] = {}
        for key in ASSET_METADATA_KEYS:
            val = row.get(key)
            if val is not None and val != "":
                if key == "cost":
                    meta[key] = float(val)
                else:
                    meta[key] = val
        return meta

    def _latest_analysis_for_asset(self, asset_id: str) -> dict | None:
        result = (
            self._table("asset_analyses")
            .select("*")
            .eq("asset_id", asset_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        return rows[0] if rows else None

    def _summary_from_row(self, row: dict) -> SaasAssetSummary:
        latest = self._latest_analysis_for_asset(row["id"])
        summary_fields: dict[str, str | None] = {}
        latest_id = None
        failure_summary = None
        ai_status = row.get("ai_status") or "pending"
        if ai_status == "analyzing":
            summary_fields = {}
            failure_summary = None
            latest_id = None
        elif latest:
            latest_id = latest.get("id")
            failure_summary = latest.get("failure_summary")
            resp = latest.get("response_json") or {}
            if isinstance(resp, dict):
                summary_fields = extract_summary_fields(resp)

        cost = row.get("cost")
        return SaasAssetSummary(
            id=row["id"],
            assetid=row.get("assetid") or "",
            assetname=row.get("assetname"),
            description=row.get("description"),
            tagnumber=row.get("tagnumber"),
            assetnumber=row.get("assetnumber"),
            assetclassid=row.get("assetclassid"),
            assetclassname=row.get("assetclassname"),
            categoryid=row.get("categoryid"),
            categoryname=row.get("categoryname"),
            subcategoryid=row.get("subcategoryid"),
            subcategoryname=row.get("subcategoryname"),
            makemodelid=row.get("makemodelid"),
            makemodelname=row.get("makemodelname"),
            companyid=row.get("companyid"),
            company=row.get("company"),
            customerid=row.get("customerid"),
            assettaggingdetailid=row.get("assettaggingdetailid"),
            cost=float(cost) if cost is not None else None,
            acquisitiondate=row.get("acquisitiondate"),
            ai_status=ai_status,
            asset_image_url=self._signed_url(row.get("asset_image_path")),
            barcode_image_url=self._signed_url(row.get("barcode_image_path")),
            created_at=self._iso(row.get("created_at")),
            updated_at=self._iso(row.get("updated_at")),
            latest_analysis_id=latest_id,
            failure_summary=failure_summary if isinstance(failure_summary, dict) else None,
            **summary_fields,
        )

    def _generate_assetid_sync(self, user_id: int) -> str:
        result = (
            self._table("registered_assets")
            .select("assetid")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(200)
            .execute()
        )
        max_num = 10000
        for row in result.data or []:
            aid = str(row.get("assetid") or "")
            m = re.match(r"^AST-(\d+)$", aid)
            if m:
                max_num = max(max_num, int(m.group(1)))
        return f"AST-{max_num + 1}"

    def _expire_session_if_needed(self, row: dict) -> dict:
        expires = self._parse_ts(row.get("expires_at"))
        if (
            expires
            and expires < datetime.now(timezone.utc)
            and row.get("status") in ("active", "images_ready")
        ):
            self._table("asset_create_sessions").update({"status": "expired"}).eq(
                "id", row["id"]
            ).execute()
            row["status"] = "expired"
        return row

    def _fetch_session_by_token_sync(self, token: str) -> dict | None:
        result = (
            self._table("asset_create_sessions")
            .select("*")
            .eq("session_token", token.strip())
            .limit(1)
            .execute()
        )
        rows = result.data or []
        if not rows:
            return None
        return self._expire_session_if_needed(rows[0])

    def _session_to_detail(self, row: dict) -> AssetCreateSessionDetail:
        return AssetCreateSessionDetail(
            session_token=row["session_token"],
            status=row.get("status") or "active",
            draft_json=row.get("draft_json") or {},
            asset_image_url=self._signed_url(row.get("asset_image_path")),
            barcode_image_url=self._signed_url(row.get("barcode_image_path")),
            expires_at=self._iso(row.get("expires_at")),
            created_asset_id=row.get("created_asset_id"),
        )

    def _create_asset_row_sync(
        self,
        user_id: int,
        metadata: dict[str, Any],
        asset_image: bytes | None,
        barcode_image: bytes | None = None,
        *,
        asset_mime: str = "image/jpeg",
        barcode_mime: str = "image/jpeg",
        existing_asset_image_path: str | None = None,
        existing_barcode_image_path: str | None = None,
    ) -> dict:
        data = {k: metadata.get(k) for k in ASSET_METADATA_KEYS}
        if not str(data.get("assetid") or "").strip():
            data["assetid"] = self._generate_assetid_sync(user_id)
        data["cost"] = self._normalize_cost(data.get("cost"))
        data["user_id"] = user_id
        data["ai_status"] = "pending"

        insert_result = self._table("registered_assets").insert(data).execute()
        row = (insert_result.data or [None])[0]
        if not row:
            raise RuntimeError("Failed to create asset")

        asset_id = row["id"]
        updates: dict[str, Any] = {}

        if asset_image:
            path = self._asset_image_path(user_id, asset_id, "asset")
            self._upload_bytes(path, asset_image, asset_mime)
            updates["asset_image_path"] = path
        elif existing_asset_image_path:
            updates["asset_image_path"] = existing_asset_image_path

        if barcode_image:
            path = self._asset_image_path(user_id, asset_id, "barcode")
            self._upload_bytes(path, barcode_image, barcode_mime)
            updates["barcode_image_path"] = path
        elif existing_barcode_image_path:
            updates["barcode_image_path"] = existing_barcode_image_path

        if updates:
            upd = self._table("registered_assets").update(updates).eq("id", asset_id).execute()
            row = (upd.data or [row])[0]

        return row

    def _log_activity_sync(
        self,
        user_id: int,
        event_type: str,
        message: str,
        *,
        asset_id: str | None = None,
        assetname: str | None = None,
        assetid: str | None = None,
        ai_status: str | None = None,
    ) -> None:
        try:
            self._table("activity_events").insert(
                {
                    "user_id": user_id,
                    "event_type": event_type,
                    "asset_id": asset_id,
                    "assetname": assetname,
                    "assetid": assetid,
                    "ai_status": ai_status,
                    "message": message,
                }
            ).execute()
        except Exception as exc:
            logger.warning("saas_activity_log_failed", error=str(exc))

    async def log_activity(self, user_id: int, event_type: str, message: str, **kwargs: Any) -> None:
        await asyncio.to_thread(self._log_activity_sync, user_id, event_type, message, **kwargs)

    def _remove_storage_paths(self, paths: list[str | None]) -> None:
        storage = self._get_client().storage.from_(self._bucket())
        for path in paths:
            if not path:
                continue
            try:
                storage.remove([path])
            except Exception as exc:
                logger.warning("saas_storage_remove_failed", path=path, error=str(exc))

    # --- async public API ---

    async def list_assets(
        self,
        user_id: int,
        *,
        limit: int = 100,
        offset: int = 0,
        query: str | None = None,
        ai_status: str | None = None,
        company: str | None = None,
        sort: str = "created_at",
        order: str = "desc",
    ) -> tuple[list[SaasAssetSummary], int]:
        return await asyncio.to_thread(
            self._list_assets_sync,
            user_id,
            limit,
            offset,
            query,
            ai_status,
            company,
            sort,
            order,
        )

    def _list_assets_sync(
        self,
        user_id: int,
        limit: int,
        offset: int,
        query: str | None,
        ai_status: str | None = None,
        company: str | None = None,
        sort: str = "created_at",
        order: str = "desc",
    ) -> tuple[list[SaasAssetSummary], int]:
        q = self._table("registered_assets").select("*", count="exact").eq("user_id", user_id)
        if query and query.strip():
            term = query.strip()
            q = q.or_(
                f"assetname.ilike.%{term}%,assetid.ilike.%{term}%,tagnumber.ilike.%{term}%,company.ilike.%{term}%"
            )
        if ai_status and ai_status.strip():
            q = q.eq("ai_status", ai_status.strip())
        if company and company.strip():
            q = q.ilike("company", f"%{company.strip()}%")

        sort_field = sort if sort in self.SORTABLE_FIELDS else "created_at"
        descending = order.lower() != "asc"
        result = (
            q.order(sort_field, desc=descending).range(offset, offset + limit - 1).execute()
        )
        rows = result.data or []
        total = result.count if result.count is not None else len(rows)
        return [self._summary_from_row(r) for r in rows], total

    async def get_asset(self, user_id: int, asset_id: str) -> SaasAssetDetailResponse | None:
        return await asyncio.to_thread(self._get_asset_sync, user_id, asset_id)

    def _get_asset_sync(self, user_id: int, asset_id: str) -> SaasAssetDetailResponse | None:
        result = (
            self._table("registered_assets")
            .select("*")
            .eq("id", asset_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        if not rows:
            return None
        summary = self._summary_from_row(rows[0])
        latest_row = self._latest_analysis_for_asset(asset_id)
        latest = None
        if latest_row:
            latest = SaasAnalysisItem(
                id=latest_row["id"],
                asset_id=latest_row["asset_id"],
                request_id=latest_row.get("request_id"),
                ai_status=latest_row.get("ai_status") or "error",
                failure_summary=latest_row.get("failure_summary"),
                response_time_seconds=float(latest_row["response_time_seconds"])
                if latest_row.get("response_time_seconds") is not None
                else None,
                created_at=self._iso(latest_row.get("created_at")),
                response_json=latest_row.get("response_json"),
            )
        return SaasAssetDetailResponse(asset=summary, latest_analysis=latest)

    async def create_asset(
        self,
        user_id: int,
        metadata: dict[str, Any],
        asset_image: bytes | None,
        barcode_image: bytes | None = None,
        *,
        asset_mime: str = "image/jpeg",
        barcode_mime: str = "image/jpeg",
    ) -> CreateAssetResponse:
        meta = dict(metadata)
        meta["_has_asset_image"] = bool(asset_image)
        validate_create_metadata(meta)
        row = await asyncio.to_thread(
            self._create_asset_row_sync,
            user_id,
            meta,
            asset_image,
            barcode_image,
            asset_mime=asset_mime,
            barcode_mime=barcode_mime,
        )
        await self.log_activity(
            user_id,
            "asset_created",
            f"Asset {row.get('assetname') or row['assetid']} created",
            asset_id=row["id"],
            assetname=row.get("assetname"),
            assetid=row.get("assetid"),
            ai_status="pending",
        )
        return CreateAssetResponse(id=row["id"], assetid=row["assetid"], ai_status="analyzing")

    async def register_asset(
        self,
        user_id: int,
        metadata: dict[str, Any],
    ) -> CreateAssetResponse:
        """Create asset record without images; stays pending until photos + analyze."""
        meta = dict(metadata)
        validate_create_metadata(meta, require_asset_image=False)
        row = await asyncio.to_thread(
            self._create_asset_row_sync,
            user_id,
            meta,
            None,
            None,
        )
        await self.log_activity(
            user_id,
            "asset_created",
            f"Asset {row.get('assetname') or row['assetid']} registered (awaiting photos)",
            asset_id=row["id"],
            assetname=row.get("assetname"),
            assetid=row.get("assetid"),
            ai_status="pending",
        )
        return CreateAssetResponse(id=row["id"], assetid=row["assetid"], ai_status="pending")

    async def set_ai_status(self, asset_id: str, status: str) -> None:
        await asyncio.to_thread(
            self._table("registered_assets").update({"ai_status": status}).eq("id", asset_id).execute
        )

    async def run_analysis(
        self, user_id: int, asset_id: str, metadata_patch: dict[str, Any] | None = None
    ) -> str:
        return await asyncio.to_thread(
            self._run_analysis_sync, user_id, asset_id, metadata_patch
        )

    def _run_analysis_sync(
        self, user_id: int, asset_id: str, metadata_patch: dict[str, Any] | None = None
    ) -> str:
        result = (
            self._table("registered_assets")
            .select("*")
            .eq("id", asset_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        if not rows:
            raise ValueError("Asset not found")
        row = rows[0]

        if metadata_patch:
            updates = {
                k: metadata_patch[k]
                for k in ASSET_METADATA_KEYS
                if k in metadata_patch and metadata_patch[k] is not None
            }
            if "cost" in updates:
                updates["cost"] = self._normalize_cost(updates["cost"])
            if updates:
                upd = (
                    self._table("registered_assets")
                    .update(updates)
                    .eq("id", asset_id)
                    .eq("user_id", user_id)
                    .execute()
                )
                row = (upd.data or [row])[0]

        self._table("registered_assets").update({"ai_status": "analyzing"}).eq("id", asset_id).execute()

        metadata = self._row_to_metadata(row)
        asset_bytes = None
        barcode_bytes = None
        if row.get("asset_image_path"):
            try:
                asset_bytes = self._download_bytes(row["asset_image_path"])
            except Exception as exc:
                logger.warning("saas_download_asset_image_failed", error=str(exc))
        if row.get("barcode_image_path"):
            try:
                barcode_bytes = self._download_bytes(row["barcode_image_path"])
            except Exception as exc:
                logger.warning("saas_download_barcode_image_failed", error=str(exc))

        try:
            response, request_id, elapsed = asyncio.run(
                analyze_asset_with_tagging_ai(self.settings, metadata, asset_bytes, barcode_bytes)
            )
        except Exception as exc:
            logger.exception("saas_tagging_ai_failed", asset_id=asset_id, error=str(exc))
            self._table("registered_assets").update({"ai_status": "error"}).eq("id", asset_id).execute()
            self._table("asset_analyses").insert(
                {
                    "asset_id": asset_id,
                    "user_id": user_id,
                    "request_id": None,
                    "response_json": {"error": str(exc)},
                    "ai_status": "error",
                    "failure_summary": {"error": str(exc)},
                    "response_time_seconds": None,
                }
            ).execute()
            return "error"

        ai_status, failure_summary = compute_ai_status(response, metadata)
        self._table("asset_analyses").insert(
            {
                "asset_id": asset_id,
                "user_id": user_id,
                "request_id": request_id,
                "response_json": response,
                "ai_status": ai_status,
                "failure_summary": failure_summary,
                "response_time_seconds": round(elapsed, 2),
            }
        ).execute()
        self._table("registered_assets").update({"ai_status": ai_status}).eq("id", asset_id).execute()
        self._log_activity_sync(
            user_id,
            "analysis_complete",
            f"AI {ai_status} for {row.get('assetname') or row.get('assetid')}",
            asset_id=asset_id,
            assetname=row.get("assetname"),
            assetid=row.get("assetid"),
            ai_status=ai_status,
        )
        return ai_status

    async def list_analyses(self, user_id: int, asset_id: str) -> list[SaasAnalysisItem]:
        return await asyncio.to_thread(self._list_analyses_sync, user_id, asset_id)

    def _list_analyses_sync(self, user_id: int, asset_id: str) -> list[SaasAnalysisItem]:
        result = (
            self._table("asset_analyses")
            .select("*")
            .eq("asset_id", asset_id)
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        items = []
        for row in result.data or []:
            items.append(
                SaasAnalysisItem(
                    id=row["id"],
                    asset_id=row["asset_id"],
                    request_id=row.get("request_id"),
                    ai_status=row.get("ai_status") or "error",
                    failure_summary=row.get("failure_summary"),
                    response_time_seconds=float(row["response_time_seconds"])
                    if row.get("response_time_seconds") is not None
                    else None,
                    created_at=self._iso(row.get("created_at")),
                    response_json=row.get("response_json"),
                )
            )
        return items

    async def get_analysis(
        self, user_id: int, asset_id: str, analysis_id: str
    ) -> SaasAnalysisItem | None:
        return await asyncio.to_thread(self._get_analysis_sync, user_id, asset_id, analysis_id)

    def _get_analysis_sync(
        self, user_id: int, asset_id: str, analysis_id: str
    ) -> SaasAnalysisItem | None:
        result = (
            self._table("asset_analyses")
            .select("*")
            .eq("id", analysis_id)
            .eq("asset_id", asset_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        if not rows:
            return None
        row = rows[0]
        return SaasAnalysisItem(
            id=row["id"],
            asset_id=row["asset_id"],
            request_id=row.get("request_id"),
            ai_status=row.get("ai_status") or "error",
            failure_summary=row.get("failure_summary"),
            response_time_seconds=float(row["response_time_seconds"])
            if row.get("response_time_seconds") is not None
            else None,
            created_at=self._iso(row.get("created_at")),
            response_json=row.get("response_json"),
        )

    async def create_asset_session(
        self, user_id: int, draft_json: dict[str, Any] | None = None
    ) -> AssetCreateSessionDetail:
        return await asyncio.to_thread(self._create_asset_session_sync, user_id, draft_json or {})

    def _create_asset_session_sync(
        self, user_id: int, draft_json: dict[str, Any]
    ) -> AssetCreateSessionDetail:
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=self.settings.saas_asset_create_session_ttl_minutes
        )
        row = {
            "session_token": token,
            "user_id": user_id,
            "status": "active",
            "draft_json": draft_json,
            "expires_at": expires_at.isoformat(),
        }
        result = self._table("asset_create_sessions").insert(row).execute()
        created = (result.data or [None])[0]
        if not created:
            raise RuntimeError("Failed to create asset session")
        return self._session_to_detail(created)

    async def get_asset_session(self, token: str) -> AssetCreateSessionDetail | None:
        return await asyncio.to_thread(self._get_asset_session_sync, token)

    def _get_asset_session_sync(self, token: str) -> AssetCreateSessionDetail | None:
        row = self._fetch_session_by_token_sync(token)
        if not row:
            return None
        if row.get("status") == "completed":
            raise SessionCompletedError("Session already used")
        if row.get("status") == "expired":
            raise SessionExpiredError("Session expired")
        return self._session_to_detail(row)

    async def upload_session_image(
        self,
        token: str,
        image_kind: str,
        image_bytes: bytes,
        *,
        mime_type: str = "image/jpeg",
    ) -> AssetCreateSessionDetail:
        return await asyncio.to_thread(
            self._upload_session_image_sync, token, image_kind, image_bytes, mime_type
        )

    def _upload_session_image_sync(
        self, token: str, image_kind: str, image_bytes: bytes, mime_type: str
    ) -> AssetCreateSessionDetail:
        if image_kind not in ("asset", "barcode"):
            raise ValueError("image_kind must be asset or barcode")

        row = self._fetch_session_by_token_sync(token)
        if not row:
            raise ValueError("Session not found")
        if row.get("status") == "completed":
            raise SessionCompletedError("Session already used")
        if row.get("status") == "expired":
            raise SessionExpiredError("Session expired")

        path_key = "asset_image_path" if image_kind == "asset" else "barcode_image_path"
        path = self._session_image_path(row["user_id"], row["id"], image_kind)
        self._upload_bytes(path, image_bytes, mime_type)

        updates: dict[str, Any] = {path_key: path}
        has_asset = bool(path if image_kind == "asset" else row.get("asset_image_path"))
        has_barcode = bool(path if image_kind == "barcode" else row.get("barcode_image_path"))
        if has_asset:
            updates["status"] = "images_ready"

        result = (
            self._table("asset_create_sessions")
            .update(updates)
            .eq("id", row["id"])
            .execute()
        )
        updated = (result.data or [row])[0]
        return self._session_to_detail(updated)

    async def complete_asset_session(
        self, token: str, metadata: dict[str, Any]
    ) -> CompleteAssetSessionResponse:
        return await asyncio.to_thread(self._complete_asset_session_sync, token, metadata)

    def _complete_asset_session_sync(
        self, token: str, metadata: dict[str, Any]
    ) -> CompleteAssetSessionResponse:
        row = self._fetch_session_by_token_sync(token)
        if not row:
            raise ValueError("Session not found")
        if row.get("status") == "completed":
            raise SessionCompletedError("Session already used")
        if row.get("status") == "expired":
            raise SessionExpiredError("Session expired")

        draft = row.get("draft_json") or {}
        if draft.get("_session_mode") == "images_only":
            raise ValueError(
                "This session is for photos only — complete the asset from the web create form"
            )

        merged = {**draft, **metadata}
        merged["_has_asset_image"] = bool(row.get("asset_image_path"))
        validate_create_metadata(merged)

        asset_image = None
        barcode_image = None
        if row.get("asset_image_path"):
            asset_image = self._download_bytes(row["asset_image_path"])
        if row.get("barcode_image_path"):
            barcode_image = self._download_bytes(row["barcode_image_path"])

        created = self._create_asset_row_sync(
            row["user_id"],
            merged,
            asset_image,
            barcode_image,
            existing_asset_image_path=row.get("asset_image_path"),
            existing_barcode_image_path=row.get("barcode_image_path"),
        )

        self._table("asset_create_sessions").update(
            {
                "status": "completed",
                "created_asset_id": created["id"],
            }
        ).eq("id", row["id"]).execute()

        self._table("registered_assets").update({"ai_status": "analyzing"}).eq(
            "id", created["id"]
        ).execute()

        self._table("registered_assets").update({"ai_status": "analyzing"}).eq(
            "id", created["id"]
        ).execute()

        self._log_activity_sync(
            row["user_id"],
            "asset_created",
            f"Asset {created.get('assetname') or created['assetid']} created via mobile",
            asset_id=created["id"],
            assetname=created.get("assetname"),
            assetid=created.get("assetid"),
            ai_status="analyzing",
        )

        return CompleteAssetSessionResponse(
            asset_id=created["id"],
            assetid=created["assetid"],
            ai_status="analyzing",
        )

    async def update_asset(
        self,
        user_id: int,
        asset_id: str,
        metadata: dict[str, Any],
        *,
        asset_image: bytes | None = None,
        barcode_image: bytes | None = None,
        asset_mime: str = "image/jpeg",
        barcode_mime: str = "image/jpeg",
    ) -> SaasAssetSummary | None:
        return await asyncio.to_thread(
            self._update_asset_sync,
            user_id,
            asset_id,
            metadata,
            asset_image,
            barcode_image,
            asset_mime,
            barcode_mime,
        )

    def _update_asset_sync(
        self,
        user_id: int,
        asset_id: str,
        metadata: dict[str, Any],
        asset_image: bytes | None,
        barcode_image: bytes | None,
        asset_mime: str,
        barcode_mime: str,
    ) -> SaasAssetSummary | None:
        result = (
            self._table("registered_assets")
            .select("*")
            .eq("id", asset_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        if not rows:
            return None
        row = rows[0]

        updates = {
            k: metadata[k] for k in ASSET_METADATA_KEYS if k in metadata and metadata[k] is not None
        }
        if "cost" in updates:
            updates["cost"] = self._normalize_cost(updates["cost"])
        if updates:
            upd = (
                self._table("registered_assets")
                .update(updates)
                .eq("id", asset_id)
                .execute()
            )
            row = (upd.data or [row])[0]

        if asset_image:
            path = self._asset_image_path(user_id, asset_id, "asset")
            self._upload_bytes(path, asset_image, asset_mime)
            upd = (
                self._table("registered_assets")
                .update({"asset_image_path": path})
                .eq("id", asset_id)
                .execute()
            )
            row = (upd.data or [row])[0]
        if barcode_image:
            path = self._asset_image_path(user_id, asset_id, "barcode")
            self._upload_bytes(path, barcode_image, barcode_mime)
            upd = (
                self._table("registered_assets")
                .update({"barcode_image_path": path})
                .eq("id", asset_id)
                .execute()
            )
            row = (upd.data or [row])[0]

        return self._summary_from_row(row)

    async def delete_asset(self, user_id: int, asset_id: str) -> bool:
        return await asyncio.to_thread(self._delete_asset_sync, user_id, asset_id)

    def _delete_asset_sync(self, user_id: int, asset_id: str) -> bool:
        result = (
            self._table("registered_assets")
            .select("*")
            .eq("id", asset_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        if not rows:
            return False
        row = rows[0]
        self._remove_storage_paths([row.get("asset_image_path"), row.get("barcode_image_path")])
        self._log_activity_sync(
            user_id,
            "asset_deleted",
            f"Asset {row.get('assetname') or row.get('assetid')} deleted",
            asset_id=asset_id,
            assetname=row.get("assetname"),
            assetid=row.get("assetid"),
        )
        self._table("registered_assets").delete().eq("id", asset_id).eq("user_id", user_id).execute()
        return True

    async def bulk_delete(self, user_id: int, asset_ids: list[str]) -> int:
        return await asyncio.to_thread(self._bulk_delete_sync, user_id, asset_ids)

    def _bulk_delete_sync(self, user_id: int, asset_ids: list[str]) -> int:
        count = 0
        for aid in asset_ids:
            if self._delete_asset_sync(user_id, aid):
                count += 1
        return count

    async def bulk_analyze(self, user_id: int, asset_ids: list[str]) -> list[str]:
        return await asyncio.to_thread(self._bulk_analyze_sync, user_id, asset_ids)

    def _bulk_analyze_sync(self, user_id: int, asset_ids: list[str]) -> list[str]:
        queued: list[str] = []
        for aid in asset_ids:
            result = (
                self._table("registered_assets")
                .select("id")
                .eq("id", aid)
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            if result.data:
                self._table("registered_assets").update({"ai_status": "analyzing"}).eq(
                    "id", aid
                ).execute()
                queued.append(aid)
        return queued

    async def get_dashboard_stats(self, user_id: int) -> dict[str, int]:
        return await asyncio.to_thread(self._get_dashboard_stats_sync, user_id)

    def _get_dashboard_stats_sync(self, user_id: int) -> dict[str, int]:
        result = (
            self._table("registered_assets")
            .select("ai_status")
            .eq("user_id", user_id)
            .execute()
        )
        stats = {
            "total": 0,
            "pass_count": 0,
            "fail_count": 0,
            "pending": 0,
            "error": 0,
            "analyzing": 0,
        }
        for row in result.data or []:
            stats["total"] += 1
            status = row.get("ai_status") or "pending"
            if status == "pass":
                stats["pass_count"] += 1
            elif status == "fail":
                stats["fail_count"] += 1
            elif status == "error":
                stats["error"] += 1
            elif status == "analyzing":
                stats["analyzing"] += 1
            else:
                stats["pending"] += 1
        return stats

    async def list_activity(self, user_id: int, *, limit: int = 50) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._list_activity_sync, user_id, limit)

    def _list_activity_sync(self, user_id: int, limit: int) -> list[dict[str, Any]]:
        result = (
            self._table("activity_events")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        items = []
        for row in result.data or []:
            items.append(
                {
                    "id": row["id"],
                    "event_type": row.get("event_type"),
                    "asset_id": row.get("asset_id"),
                    "assetname": row.get("assetname"),
                    "assetid": row.get("assetid"),
                    "ai_status": row.get("ai_status"),
                    "message": row.get("message"),
                    "created_at": self._iso(row.get("created_at")),
                }
            )
        return items

    async def save_web_draft(
        self,
        user_id: int,
        draft_json: dict[str, Any],
        *,
        draft_id: str | None = None,
        title: str | None = None,
        asset_image_path: str | None = None,
        barcode_image_path: str | None = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._save_web_draft_sync,
            user_id,
            draft_json,
            draft_id,
            title,
            asset_image_path,
            barcode_image_path,
        )

    def _save_web_draft_sync(
        self,
        user_id: int,
        draft_json: dict[str, Any],
        draft_id: str | None,
        title: str | None,
        asset_image_path: str | None,
        barcode_image_path: str | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "user_id": user_id,
            "draft_json": draft_json,
            "title": title,
        }
        if asset_image_path is not None:
            payload["asset_image_path"] = asset_image_path
        if barcode_image_path is not None:
            payload["barcode_image_path"] = barcode_image_path

        if draft_id:
            result = (
                self._table("web_drafts")
                .update(payload)
                .eq("id", draft_id)
                .eq("user_id", user_id)
                .execute()
            )
            row = (result.data or [None])[0]
            if not row:
                raise ValueError("Draft not found")
        else:
            result = self._table("web_drafts").insert(payload).execute()
            row = (result.data or [None])[0]
            if not row:
                raise RuntimeError("Failed to save draft")
        return self._draft_to_item(row)

    def _draft_to_item(self, row: dict) -> dict[str, Any]:
        return {
            "id": row["id"],
            "title": row.get("title"),
            "draft_json": row.get("draft_json") or {},
            "asset_image_url": self._signed_url(row.get("asset_image_path")),
            "barcode_image_url": self._signed_url(row.get("barcode_image_path")),
            "updated_at": self._iso(row.get("updated_at")),
        }

    async def list_web_drafts(self, user_id: int) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._list_web_drafts_sync, user_id)

    def _list_web_drafts_sync(self, user_id: int) -> list[dict[str, Any]]:
        result = (
            self._table("web_drafts")
            .select("*")
            .eq("user_id", user_id)
            .order("updated_at", desc=True)
            .execute()
        )
        return [self._draft_to_item(r) for r in result.data or []]

    async def get_web_draft(self, user_id: int, draft_id: str) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._get_web_draft_sync, user_id, draft_id)

    def _get_web_draft_sync(self, user_id: int, draft_id: str) -> dict[str, Any] | None:
        result = (
            self._table("web_drafts")
            .select("*")
            .eq("id", draft_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        return self._draft_to_item(rows[0]) if rows else None

    async def delete_web_draft(self, user_id: int, draft_id: str) -> bool:
        return await asyncio.to_thread(self._delete_web_draft_sync, user_id, draft_id)

    def _delete_web_draft_sync(self, user_id: int, draft_id: str) -> bool:
        result = (
            self._table("web_drafts")
            .delete()
            .eq("id", draft_id)
            .eq("user_id", user_id)
            .execute()
        )
        return bool(result.data)

    async def export_assets_csv(
        self,
        user_id: int,
        *,
        query: str | None = None,
        ai_status: str | None = None,
        company: str | None = None,
    ) -> str:
        return await asyncio.to_thread(
            self._export_assets_csv_sync, user_id, query, ai_status, company
        )

    def _export_assets_csv_sync(
        self,
        user_id: int,
        query: str | None,
        ai_status: str | None,
        company: str | None,
    ) -> str:
        items, _ = self._list_assets_sync(
            user_id, 10000, 0, query, ai_status, company, "created_at", "desc"
        )
        output = io.StringIO()
        fieldnames = list(ASSET_METADATA_KEYS) + ["ai_status", "created_at", "updated_at"]
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for item in items:
            row = {k: getattr(item, k, None) for k in ASSET_METADATA_KEYS}
            row["ai_status"] = item.ai_status
            row["created_at"] = item.created_at
            row["updated_at"] = item.updated_at
            writer.writerow(row)
        return output.getvalue()


class SessionCompletedError(Exception):
    pass


class SessionExpiredError(Exception):
    pass


_repository: SaasAssetsRepository | None = None


def get_saas_assets_repository(settings: Settings) -> SaasAssetsRepository:
    global _repository
    if _repository is None or _repository.settings is not settings:
        _repository = SaasAssetsRepository(settings)
    return _repository
