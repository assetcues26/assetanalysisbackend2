"""Persist analyses to Supabase Postgres + Storage (server-side only)."""

from __future__ import annotations

import asyncio
import base64
import concurrent.futures
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import structlog

from app.config import Settings
from app.models.history import HistoryDetailResponse, HistoryListItem, ImageUrls
from app.models.responses import AnalyzeResponse, UnifiedViewMethod

if TYPE_CHECKING:
    from app.models.pipeline import ProcessedImage

logger = structlog.get_logger()

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def is_valid_entry_id(entry_id: str) -> bool:
    return bool(entry_id and _UUID_RE.match(entry_id.strip()))


class HistoryRepository:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client: Any = None

    @property
    def enabled(self) -> bool:
        return (
            self.settings.supabase_persist_enabled
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
        return self.settings.supabase_storage_bucket.strip() or "analysis-images"

    def _storage_prefix(self, user_id: int, entry_id: str) -> str:
        return f"user_{user_id}/{entry_id}"

    def _upload_path(self, user_id: int, entry_id: str, filename: str) -> str:
        return f"{self._storage_prefix(user_id, entry_id)}/{filename}"

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
            logger.warning("signed_url_failed", path=storage_path, error=str(exc))
            return None

    def _signed_urls_batch(self, paths: list[str]) -> dict[str, str]:
        """Sign many storage paths in parallel."""
        unique = list(dict.fromkeys(path for path in paths if path))
        if not unique:
            return {}

        max_workers = min(len(unique), 10)
        signed: dict[str, str] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_path = {
                executor.submit(self._signed_url, path): path for path in unique
            }
            for future in concurrent.futures.as_completed(future_to_path):
                path = future_to_path[future]
                try:
                    url = future.result()
                    if url:
                        signed[path] = url
                except Exception as exc:
                    logger.warning("signed_url_batch_failed", path=path, error=str(exc))
        return signed

    def _first_image_paths_for_analyses(
        self,
        client: Any,
        analysis_ids: list[str],
    ) -> dict[str, str]:
        if not analysis_ids:
            return {}

        images_result = (
            client.table("analysis_images")
            .select("analysis_id, storage_path, sort_order")
            .in_("analysis_id", analysis_ids)
            .order("sort_order")
            .execute()
        )
        first_by_id: dict[str, str] = {}
        for img in images_result.data or []:
            analysis_id = img.get("analysis_id")
            storage_path = img.get("storage_path")
            if analysis_id and storage_path and analysis_id not in first_by_id:
                first_by_id[analysis_id] = storage_path
        return first_by_id

    def _upload_bytes(self, path: str, data: bytes, mime_type: str = "image/jpeg") -> None:
        storage = self._get_client().storage.from_(self._bucket())
        storage.upload(
            path,
            data,
            {"content-type": mime_type, "upsert": "true"},
        )

    def _remove_prefix(self, prefix: str) -> None:
        storage = self._get_client().storage.from_(self._bucket())
        try:
            listing = storage.list(prefix)
        except Exception as exc:
            logger.warning("storage_list_failed", prefix=prefix, error=str(exc))
            return

        paths: list[str] = []
        for item in listing or []:
            name = item.get("name") if isinstance(item, dict) else None
            if name:
                paths.append(f"{prefix}/{name}")

        if paths:
            try:
                storage.remove(paths)
            except Exception as exc:
                logger.warning("storage_remove_failed", paths=paths, error=str(exc))

    def _decode_collage_bytes(self, collage_base64: str | None) -> bytes | None:
        if not collage_base64:
            return None
        raw = collage_base64
        if raw.startswith("data:"):
            _, _, raw = raw.partition(",")
        try:
            return base64.b64decode(raw)
        except Exception:
            return None

    def _build_result_json(
        self,
        response: AnalyzeResponse,
        *,
        processing_mode: str | None,
        api_route: str | None,
    ) -> dict[str, Any]:
        data = response.model_dump(mode="json")
        data.pop("collage_base64", None)
        data.pop("entry_id", None)
        data.pop("saved_to_db", None)
        data.pop("image_urls", None)
        if processing_mode:
            data["processing_mode"] = processing_mode
        if api_route:
            data["api_route"] = api_route
        data["processed_at"] = datetime.now(timezone.utc).isoformat()
        return data

    def _save_sync(
        self,
        *,
        user_id: int,
        request_id: str,
        response: AnalyzeResponse,
        processed_images: list[ProcessedImage],
        method: UnifiedViewMethod,
        processing_mode: str | None,
        api_route: str | None,
    ) -> ImageUrls:
        entry_id = request_id
        prefix = self._storage_prefix(user_id, entry_id)
        self._remove_prefix(prefix)

        upload_paths: list[tuple[int, str, str, int]] = []
        for img in processed_images:
            sort_order = img.index + 1
            filename = f"upload_{sort_order:02d}.jpg"
            path = self._upload_path(user_id, entry_id, filename)
            self._upload_bytes(path, img.original_bytes)
            upload_paths.append((sort_order, path, filename, len(img.original_bytes)))

        collage_path: str | None = None
        collage_bytes = self._decode_collage_bytes(response.collage_base64)
        if collage_bytes:
            collage_path = self._upload_path(user_id, entry_id, "collage.jpg")
            self._upload_bytes(collage_path, collage_bytes)

        result_json = self._build_result_json(
            response,
            processing_mode=processing_mode,
            api_route=api_route,
        )
        asset = response.asset
        identifiers = response.identifiers
        row = {
            "entry_id": entry_id,
            "user_id": user_id,
            "request_id": request_id,
            "asset_name": asset.name,
            "asset_tag": identifiers.asset_tag_number_raw or identifiers.asset_tag_number,
            "condition_grade": response.condition.grade,
            "analysis_method": method.value,
            "processing_mode": processing_mode,
            "images_analyzed": response.images_analyzed,
            "processed_at": result_json.get("processed_at"),
            "result_json": result_json,
            "collage_path": collage_path,
        }

        client = self._get_client()
        inserted = client.table("analyses").insert(row).execute()
        analysis_id = None
        if inserted.data:
            analysis_id = inserted.data[0].get("id")

        if analysis_id:
            client.table("analysis_images").delete().eq("analysis_id", analysis_id).execute()
            image_rows = [
                {
                    "analysis_id": analysis_id,
                    "user_id": user_id,
                    "sort_order": sort_order,
                    "storage_path": path,
                    "file_name": filename,
                    "mime_type": "image/jpeg",
                    "byte_size": byte_size,
                }
                for sort_order, path, filename, byte_size in upload_paths
            ]
            if image_rows:
                client.table("analysis_images").insert(image_rows).execute()

        preview_urls = [url for url in (self._signed_url(p) for _, p, _, _ in upload_paths) if url]
        merged_url = self._signed_url(collage_path) if collage_path else None
        return ImageUrls(preview_urls=preview_urls, merged_image_url=merged_url)

    async def save_analysis(
        self,
        *,
        user_id: int,
        request_id: str,
        response: AnalyzeResponse,
        processed_images: list[ProcessedImage],
        method: UnifiedViewMethod,
        processing_mode: str | None = None,
        api_route: str | None = None,
    ) -> tuple[str, bool, ImageUrls | None]:
        if not self.enabled:
            return request_id, False, None

        try:
            image_urls = await asyncio.to_thread(
                self._save_sync,
                user_id=user_id,
                request_id=request_id,
                response=response,
                processed_images=processed_images,
                method=method,
                processing_mode=processing_mode,
                api_route=api_route,
            )
            logger.info(
                "analysis_persisted",
                request_id=request_id,
                user_id=user_id,
                images=len(processed_images),
            )
            return request_id, True, image_urls
        except Exception as exc:
            logger.error(
                "analysis_persist_failed",
                request_id=request_id,
                error=str(exc),
            )
            return request_id, False, None

    def _list_sync(
        self,
        *,
        user_id: int,
        limit: int,
        offset: int,
        query: str | None,
    ) -> tuple[list[HistoryListItem], int]:
        client = self._get_client()
        q = (
            client.table("analyses")
            .select(
                "id,entry_id,request_id,asset_name,asset_tag,condition_grade,"
                "analysis_method,processing_mode,images_analyzed,processed_at,collage_path",
                count="exact",
            )
            .eq("user_id", user_id)
            .order("processed_at", desc=True)
            .range(offset, offset + limit - 1)
        )
        if query and query.strip():
            term = query.strip().replace(",", " ")
            q = q.or_(f"asset_name.ilike.%{term}%,asset_tag.ilike.%{term}%")

        result = q.execute()
        rows = result.data or []
        count = result.count if result.count is not None else len(rows)

        analysis_ids = [row["id"] for row in rows if row.get("id")]
        first_image_paths = self._first_image_paths_for_analyses(client, analysis_ids)

        preview_paths: list[str | None] = []
        paths_to_sign: list[str] = []
        for row in rows:
            analysis_id = row.get("id")
            path = first_image_paths.get(analysis_id) if analysis_id else None
            if not path and row.get("collage_path"):
                path = row["collage_path"]
            preview_paths.append(path)
            if path:
                paths_to_sign.append(path)

        signed_urls = self._signed_urls_batch(paths_to_sign)

        items: list[HistoryListItem] = []
        for row, path in zip(rows, preview_paths):
            preview_url = signed_urls.get(path) if path else None

            processed_at = row.get("processed_at")
            if isinstance(processed_at, datetime):
                processed_at = processed_at.isoformat()

            items.append(
                HistoryListItem(
                    entry_id=row["entry_id"],
                    request_id=row["request_id"],
                    asset_name=row.get("asset_name"),
                    asset_tag=row.get("asset_tag"),
                    condition_grade=row.get("condition_grade"),
                    analysis_method=row.get("analysis_method"),
                    processing_mode=row.get("processing_mode"),
                    images_analyzed=row.get("images_analyzed") or 0,
                    processed_at=str(processed_at or ""),
                    preview_url=preview_url,
                )
            )
        return items, count

    async def list_analyses(
        self,
        *,
        user_id: int,
        limit: int = 100,
        offset: int = 0,
        query: str | None = None,
    ) -> tuple[list[HistoryListItem], int]:
        if not self.enabled:
            return [], 0
        return await asyncio.to_thread(
            self._list_sync,
            user_id=user_id,
            limit=limit,
            offset=offset,
            query=query,
        )

    def _get_sync(self, *, user_id: int, entry_id: str) -> HistoryDetailResponse | None:
        client = self._get_client()
        row = (
            client.table("analyses")
            .select("*")
            .eq("user_id", user_id)
            .or_(f"entry_id.eq.{entry_id},request_id.eq.{entry_id}")
            .limit(1)
            .execute()
        )
        if not row.data:
            return None

        analysis = row.data[0]
        images = (
            client.table("analysis_images")
            .select("storage_path,sort_order")
            .eq("analysis_id", analysis["id"])
            .order("sort_order")
            .execute()
        )
        preview_urls = [
            url
            for url in (
                self._signed_url(img["storage_path"])
                for img in (images.data or [])
            )
            if url
        ]
        merged_url = None
        collage_path = analysis.get("collage_path")
        if collage_path:
            merged_url = self._signed_url(collage_path)

        processed_at = analysis.get("processed_at")
        if isinstance(processed_at, datetime):
            processed_at = processed_at.isoformat()

        result_json = dict(analysis.get("result_json") or {})
        result_json["image_urls"] = {
            "preview_urls": preview_urls,
            "merged_image_url": merged_url,
        }

        return HistoryDetailResponse(
            entry_id=analysis["entry_id"],
            request_id=analysis["request_id"],
            processed_at=str(processed_at or ""),
            result_json=result_json,
            image_urls=ImageUrls(preview_urls=preview_urls, merged_image_url=merged_url),
        )

    async def get_analysis(self, *, user_id: int, entry_id: str) -> HistoryDetailResponse | None:
        if not self.enabled or not is_valid_entry_id(entry_id):
            return None
        return await asyncio.to_thread(self._get_sync, user_id=user_id, entry_id=entry_id)

    def _delete_sync(self, *, user_id: int, entry_id: str) -> bool:
        client = self._get_client()
        row = (
            client.table("analyses")
            .select("id,entry_id")
            .eq("user_id", user_id)
            .or_(f"entry_id.eq.{entry_id},request_id.eq.{entry_id}")
            .limit(1)
            .execute()
        )
        if not row.data:
            return False

        analysis = row.data[0]
        prefix = self._storage_prefix(user_id, analysis["entry_id"])
        self._remove_prefix(prefix)
        client.table("analyses").delete().eq("id", analysis["id"]).execute()
        return True

    async def delete_analysis(self, *, user_id: int, entry_id: str) -> bool:
        if not self.enabled or not is_valid_entry_id(entry_id):
            return False
        return await asyncio.to_thread(self._delete_sync, user_id=user_id, entry_id=entry_id)


_repository: HistoryRepository | None = None


def get_history_repository(settings: Settings) -> HistoryRepository:
    global _repository
    if _repository is None or _repository.settings is not settings:
        _repository = HistoryRepository(settings)
    return _repository
