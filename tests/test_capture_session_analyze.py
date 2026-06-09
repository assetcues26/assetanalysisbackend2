"""Unit tests for capture session analyze lock + Gemini orchestration."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import Settings
from app.models.responses import (
    AnalyzeResponse,
    AssetDetails,
    ConditionReport,
    ConfidenceScores,
    CostInfo,
    Identifiers,
    TokenUsage,
    UnifiedViewMethod,
    Valuation,
)
from app.services.capture_session_repository import CaptureSessionRepository

TOKEN = "a" * 32
SESSION_ID = str(uuid.uuid4())
USER_ID = 100


@pytest.fixture
def repo_settings():
    return Settings(
        supabase_persist_enabled=True,
        capture_session_enabled=True,
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="test-key",
        demo_user_id=USER_ID,
        max_images=10,
        min_images=1,
    )


@pytest.fixture
def repository(repo_settings):
    return CaptureSessionRepository(repo_settings)


def _active_row(image_count: int = 1) -> dict:
    return {
        "id": SESSION_ID,
        "session_token": TOKEN,
        "user_id": USER_ID,
        "status": "active",
        "processing_mode": "direct",
        "image_count": image_count,
        "expires_at": "2026-12-31T00:00:00Z",
    }


def _analyzing_row(image_count: int = 1) -> dict:
    row = _active_row(image_count)
    row["status"] = "analyzing"
    return row


def _minimal_response(request_id: str, entry_id: str) -> AnalyzeResponse:
    return AnalyzeResponse(
        request_id=request_id,
        entry_id=entry_id,
        processing_time_ms=100,
        analysis_method=UnifiedViewMethod.MULTI_IMAGE,
        images_analyzed=1,
        asset=AssetDetails(name="Test Asset"),
        condition=ConditionReport(grade="Good"),
        identifiers=Identifiers(),
        valuation=Valuation(),
        confidence=ConfidenceScores(),
        token_usage=TokenUsage(),
        cost=CostInfo(
            model="test",
            input_usd_per_1m=0.25,
            output_usd_per_1m=1.5,
            input_cost_usd=0.01,
            output_cost_usd=0.02,
            total_cost_usd=0.03,
            usd_to_inr=83.0,
            total_cost_inr=2.49,
            fx_source="test",
            fx_is_fallback=False,
        ),
    )


def _image_rows() -> list[dict]:
    return [
        {
            "id": str(uuid.uuid4()),
            "session_id": SESSION_ID,
            "sort_order": 1,
            "storage_path": f"user_{USER_ID}/sessions/{SESSION_ID}/upload_01.jpg",
            "file_name": "photo.jpg",
            "mime_type": "image/jpeg",
            "byte_size": 1200,
            "source": "mobile",
        }
    ]


@pytest.mark.asyncio
async def test_analyze_session_runs_gemini_when_lock_acquired(repository):
    analyzing_row = _analyzing_row()
    entry_id = str(uuid.uuid4())
    analyzer = MagicMock()
    request_id = str(uuid.uuid4())
    analyzer.analyze = AsyncMock(
        return_value=_minimal_response(request_id, entry_id),
    )

    with (
        patch.object(
            repository,
            "_try_lock_analyzing_sync",
            return_value=(analyzing_row, True),
        ),
        patch.object(repository, "_fetch_images", return_value=_image_rows()),
        patch.object(repository, "_download_image_bytes", return_value=b"jpeg-bytes"),
        patch.object(repository, "_complete_session_sync") as complete_mock,
    ):
        detail, error = await repository.analyze_session(
            token=TOKEN,
            user_id=USER_ID,
            analyzer=analyzer,
        )

    assert error is None
    assert detail is not None
    assert detail.status == "completed"
    assert detail.entry_id == entry_id
    analyzer.analyze.assert_awaited_once()
    complete_mock.assert_called_once_with(session_id=SESSION_ID, entry_id=entry_id)


@pytest.mark.asyncio
async def test_analyze_session_polls_when_already_analyzing(repository):
    analyzing_row = _analyzing_row()
    analyzer = MagicMock()
    analyzer.analyze = AsyncMock()

    with (
        patch.object(
            repository,
            "_try_lock_analyzing_sync",
            return_value=(analyzing_row, False),
        ),
        patch.object(repository, "_fetch_images", return_value=_image_rows()) as fetch_mock,
    ):
        detail, error = await repository.analyze_session(
            token=TOKEN,
            user_id=USER_ID,
            analyzer=analyzer,
        )

    assert error is None
    assert detail is not None
    assert detail.status == "analyzing"
    assert detail.entry_id is None
    analyzer.analyze.assert_not_awaited()
    fetch_mock.assert_called_once_with(SESSION_ID)
