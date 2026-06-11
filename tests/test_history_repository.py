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


def test_list_sync_batches_image_query_and_urls(enabled_settings):
    repo = HistoryRepository(enabled_settings)
    analysis_ids = ["aid-1", "aid-2", "aid-3"]
    rows = [
        {
            "id": analysis_ids[0],
            "entry_id": str(uuid.uuid4()),
            "request_id": "req-1",
            "asset_name": "Asset One",
            "asset_tag": "TAG1",
            "condition_grade": "Good",
            "analysis_method": "multi_image",
            "processing_mode": "direct",
            "images_analyzed": 2,
            "processed_at": "2026-01-01T00:00:00Z",
            "collage_path": None,
        },
        {
            "id": analysis_ids[1],
            "entry_id": str(uuid.uuid4()),
            "request_id": "req-2",
            "asset_name": "Asset Two",
            "asset_tag": "TAG2",
            "condition_grade": "Fair",
            "analysis_method": "collage",
            "processing_mode": "collage",
            "images_analyzed": 1,
            "processed_at": "2026-01-02T00:00:00Z",
            "collage_path": "user_100/entry-2/collage.jpg",
        },
        {
            "id": analysis_ids[2],
            "entry_id": str(uuid.uuid4()),
            "request_id": "req-3",
            "asset_name": "Asset Three",
            "asset_tag": "TAG3",
            "condition_grade": "Good",
            "analysis_method": "multi_image",
            "processing_mode": "direct",
            "images_analyzed": 0,
            "processed_at": "2026-01-03T00:00:00Z",
            "collage_path": None,
        },
    ]

    mock_client = MagicMock()
    mock_storage = MagicMock()
    mock_client.storage.from_.return_value = mock_storage
    mock_storage.create_signed_url.side_effect = (
        lambda path, _ttl: {"signedURL": f"https://signed.example/{path}"}
    )

    analyses_chain = MagicMock()
    analyses_chain.select.return_value = analyses_chain
    analyses_chain.eq.return_value = analyses_chain
    analyses_chain.order.return_value = analyses_chain
    analyses_chain.range.return_value = analyses_chain
    analyses_chain.execute.return_value = MagicMock(data=rows, count=3)

    images_chain = MagicMock()
    images_chain.select.return_value = images_chain
    images_chain.in_.return_value = images_chain
    images_chain.order.return_value = images_chain
    images_chain.execute.return_value = MagicMock(
        data=[
            {
                "analysis_id": "aid-1",
                "storage_path": "user_100/e1/upload_01.jpg",
                "sort_order": 1,
            },
            {
                "analysis_id": "aid-1",
                "storage_path": "user_100/e1/upload_02.jpg",
                "sort_order": 2,
            },
        ]
    )

    def table_router(name: str):
        if name == "analyses":
            return analyses_chain
        if name == "analysis_images":
            return images_chain
        raise AssertionError(f"unexpected table {name}")

    mock_client.table.side_effect = table_router

    with patch.object(repo, "_get_client", return_value=mock_client):
        items, total = repo._list_sync(user_id=100, limit=10, offset=0, query=None)

    assert total == 3
    assert len(items) == 3
    assert items[0].preview_url == "https://signed.example/user_100/e1/upload_01.jpg"
    assert items[1].preview_url == "https://signed.example/user_100/entry-2/collage.jpg"
    assert items[2].preview_url is None

    images_chain.in_.assert_called_once_with("analysis_id", analysis_ids)
    assert mock_storage.create_signed_url.call_count == 2
