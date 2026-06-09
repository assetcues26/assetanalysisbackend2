"""Unit tests for HistoryRepository (mocked Supabase)."""

import uuid
from unittest.mock import MagicMock, patch

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
from app.services.history_repository import HistoryRepository, is_valid_entry_id


def _minimal_response(request_id: str) -> AnalyzeResponse:
    return AnalyzeResponse(
        request_id=request_id,
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


@pytest.fixture
def enabled_settings() -> Settings:
    return Settings(
        supabase_persist_enabled=True,
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="test-key",
        demo_user_id=100,
    )


@pytest.fixture
def disabled_settings() -> Settings:
    return Settings(supabase_persist_enabled=False)


def test_is_valid_entry_id():
    assert is_valid_entry_id(str(uuid.uuid4()))
    assert not is_valid_entry_id("not-a-uuid")
    assert not is_valid_entry_id("")


@pytest.mark.asyncio
async def test_save_disabled_returns_false(disabled_settings):
    repo = HistoryRepository(disabled_settings)
    rid = str(uuid.uuid4())
    entry_id, saved, urls = await repo.save_analysis(
        user_id=100,
        request_id=rid,
        response=_minimal_response(rid),
        processed_images=[],
        method=UnifiedViewMethod.MULTI_IMAGE,
    )
    assert entry_id == rid
    assert saved is False
    assert urls is None


@pytest.mark.asyncio
async def test_save_success_mock(enabled_settings):
    repo = HistoryRepository(enabled_settings)
    rid = str(uuid.uuid4())

    mock_client = MagicMock()
    mock_storage = MagicMock()
    mock_client.storage.from_.return_value = mock_storage
    mock_storage.create_signed_url.return_value = {"signedURL": "https://signed.example/img.jpg"}
    mock_storage.list.return_value = []
    mock_client.table.return_value.insert.return_value.execute.return_value.data = [
        {"id": "aid-1"}
    ]
    mock_client.table.return_value.delete.return_value.eq.return_value.execute.return_value = None

    processed = MagicMock()
    processed.index = 0
    processed.original_bytes = b"jpeg-bytes"

    with patch.object(repo, "_get_client", return_value=mock_client):
        entry_id, saved, urls = await repo.save_analysis(
            user_id=100,
            request_id=rid,
            response=_minimal_response(rid),
            processed_images=[processed],
            method=UnifiedViewMethod.MULTI_IMAGE,
            processing_mode="direct",
            api_route="/v1/assets/analyze/multi",
        )

    assert saved is True
    assert entry_id == rid
    assert urls is not None
    assert len(urls.preview_urls) == 1
    mock_storage.upload.assert_called()


@pytest.mark.asyncio
async def test_delete_invalid_id(enabled_settings):
    repo = HistoryRepository(enabled_settings)
    assert await repo.delete_analysis(user_id=100, entry_id="bad-id") is False
