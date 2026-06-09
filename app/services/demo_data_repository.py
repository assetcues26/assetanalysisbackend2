"""Safely clear demo user data without altering schema."""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from app.config import Settings
from app.models.demo import ClearDemoDataResponse

logger = structlog.get_logger()


class DemoDataRepository:
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

    def _count_rows(self, table: str, user_id: int) -> int:
        result = (
            self._get_client()
            .table(table)
            .select("id")
            .eq("user_id", user_id)
            .execute()
        )
        return len(result.data or [])

    def _remove_storage_recursive(self, bucket: str, prefix: str) -> int:
        storage = self._get_client().storage.from_(bucket)
        removed = 0

        def walk(current: str) -> None:
            nonlocal removed
            try:
                entries = storage.list(current) or []
            except Exception as exc:
                logger.warning("demo_storage_list_failed", bucket=bucket, path=current, error=str(exc))
                return

            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                name = entry.get("name")
                if not name:
                    continue
                child = f"{current}/{name}" if current else name
                metadata = entry.get("metadata")
                if metadata is not None:
                    try:
                        storage.remove([child])
                        removed += 1
                    except Exception as exc:
                        logger.warning("demo_storage_remove_failed", path=child, error=str(exc))
                else:
                    walk(child)

        walk(prefix)
        return removed

    def _clear_sync(self, *, user_id: int) -> ClearDemoDataResponse:
        client = self._get_client()
        sessions_deleted = self._count_rows("capture_sessions", user_id)
        analyses_deleted = self._count_rows("analyses", user_id)

        # Child rows cascade via FK ON DELETE CASCADE.
        client.table("capture_sessions").delete().eq("user_id", user_id).execute()
        client.table("analyses").delete().eq("user_id", user_id).execute()

        storage_removed = 0
        prefix = f"user_{user_id}"
        analysis_bucket = self.settings.supabase_storage_bucket.strip() or "analysis-images"
        capture_bucket = self.settings.capture_storage_bucket.strip() or "capture-images"
        storage_removed += self._remove_storage_recursive(analysis_bucket, prefix)
        storage_removed += self._remove_storage_recursive(capture_bucket, prefix)

        return ClearDemoDataResponse(
            analyses_deleted=analyses_deleted,
            sessions_deleted=sessions_deleted,
            storage_objects_removed=storage_removed,
        )

    async def clear_demo_data(self, *, user_id: int) -> ClearDemoDataResponse:
        return await asyncio.to_thread(self._clear_sync, user_id=user_id)


_repository: DemoDataRepository | None = None


def get_demo_data_repository(settings: Settings) -> DemoDataRepository:
    global _repository
    if _repository is None or _repository.settings is not settings:
        _repository = DemoDataRepository(settings)
    return _repository
