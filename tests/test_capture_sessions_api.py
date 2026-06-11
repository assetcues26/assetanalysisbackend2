"""API tests for /v1/sessions routes."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.v1.sessions import get_analyzer, get_repo
from app.config import Settings, get_settings
from app.main import create_app
from app.models.capture_session import SessionDetailResponse, SessionImageItem
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


@pytest.fixture
def session_settings():
    return Settings(
        supabase_persist_enabled=True,
        capture_session_enabled=True,
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="test-key",
        demo_user_id=100,
        max_images=10,
        min_images=1,
    )


def _session_detail(
    token: str,
    status: str = "active",
    image_count: int = 0,
    market_region: str = "IN",
) -> SessionDetailResponse:
    return SessionDetailResponse(
        session_token=token,
        status=status,
        processing_mode="direct",
        market_region=market_region,
        image_count=image_count,
        max_images=10,
        total_bytes=0,
        expires_at="2026-12-31T00:00:00Z",
        images=[],
    )


def test_sessions_disabled_returns_503():
    disabled = Settings(
        supabase_persist_enabled=False,
        capture_session_enabled=False,
    )
    mock_repo = MagicMock()
    mock_repo.enabled = False

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: disabled
    app.dependency_overrides[get_repo] = lambda: mock_repo
    client = TestClient(app)

    response = client.post("/v1/sessions", json={"processing_mode": "direct"})
    assert response.status_code == 503


def test_create_session_success(session_settings):
    mock_repo = MagicMock()
    mock_repo.enabled = True
    mock_repo.create_session = AsyncMock(
        return_value=_session_detail("test-token-abc123456789012345678901234")
    )

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: session_settings
    app.dependency_overrides[get_repo] = lambda: mock_repo
    client = TestClient(app)

    response = client.post("/v1/sessions", json={"processing_mode": "direct"})
    assert response.status_code == 200
    assert response.json()["session_token"].startswith("test-token")


def test_create_session_passes_market_region(session_settings):
    mock_repo = MagicMock()
    mock_repo.enabled = True
    mock_repo.create_session = AsyncMock(
        return_value=_session_detail(
            "test-token-abc123456789012345678901234",
            market_region="US",
        )
    )

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: session_settings
    app.dependency_overrides[get_repo] = lambda: mock_repo
    client = TestClient(app)

    response = client.post(
        "/v1/sessions",
        json={"processing_mode": "direct", "market_region": "US"},
    )
    assert response.status_code == 200
    assert response.json()["market_region"] == "US"
    mock_repo.create_session.assert_awaited_once()
    call_kwargs = mock_repo.create_session.await_args.kwargs
    assert call_kwargs.get("market_region") == "US"


def test_get_session_invalid_token(session_settings):
    mock_repo = MagicMock()
    mock_repo.enabled = True

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: session_settings
    app.dependency_overrides[get_repo] = lambda: mock_repo
    client = TestClient(app)

    response = client.get("/v1/sessions/not-valid!")
    assert response.status_code == 400


def test_analyze_session_completed(session_settings):
    token = "a" * 32
    mock_repo = MagicMock()
    mock_repo.enabled = True
    entry_id = str(uuid.uuid4())
    mock_repo.analyze_session = AsyncMock(
        return_value=(
            SessionDetailResponse(
                session_token=token,
                status="completed",
                processing_mode="direct",
                market_region="IN",
                image_count=2,
                max_images=10,
                total_bytes=0,
                entry_id=entry_id,
                expires_at="2026-12-31T00:00:00Z",
                images=[],
            ),
            None,
        )
    )

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: session_settings
    app.dependency_overrides[get_repo] = lambda: mock_repo
    app.dependency_overrides[get_analyzer] = lambda: MagicMock()
    client = TestClient(app)

    response = client.post(f"/v1/sessions/{token}/analyze")
    assert response.status_code == 200
    assert response.json()["entry_id"] == entry_id


def test_analyze_session_passes_market_region(session_settings):
    token = "d" * 32
    mock_repo = MagicMock()
    mock_repo.enabled = True
    entry_id = str(uuid.uuid4())
    mock_repo.analyze_session = AsyncMock(
        return_value=(
            SessionDetailResponse(
                session_token=token,
                status="completed",
                processing_mode="direct",
                market_region="GB",
                image_count=1,
                max_images=10,
                total_bytes=0,
                entry_id=entry_id,
                expires_at="2026-12-31T00:00:00Z",
                images=[],
            ),
            None,
        )
    )

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: session_settings
    app.dependency_overrides[get_repo] = lambda: mock_repo
    app.dependency_overrides[get_analyzer] = lambda: MagicMock()
    client = TestClient(app)

    response = client.post(
        f"/v1/sessions/{token}/analyze",
        data={"market_region": "GB", "locale": "en-GB"},
    )
    assert response.status_code == 200
    mock_repo.analyze_session.assert_awaited_once()
    call_kwargs = mock_repo.analyze_session.await_args.kwargs
    assert call_kwargs.get("market_region") == "GB"


def test_cancel_session_analysis(session_settings):
    token = "c" * 32
    mock_repo = MagicMock()
    mock_repo.enabled = True
    mock_repo.cancel_analysis = AsyncMock(return_value=_session_detail(token, status="active"))

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: session_settings
    app.dependency_overrides[get_repo] = lambda: mock_repo
    client = TestClient(app)

    response = client.post(f"/v1/sessions/{token}/cancel", json={"clear_images": True})
    assert response.status_code == 200
    assert response.json()["status"] == "active"
    mock_repo.cancel_analysis.assert_awaited_once()


def test_analyze_session_analyzing(session_settings):
    token = "b" * 32
    mock_repo = MagicMock()
    mock_repo.enabled = True
    mock_repo.analyze_session = AsyncMock(
        return_value=(_session_detail(token, status="analyzing"), None)
    )

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: session_settings
    app.dependency_overrides[get_repo] = lambda: mock_repo
    app.dependency_overrides[get_analyzer] = lambda: MagicMock()
    client = TestClient(app)

    response = client.post(f"/v1/sessions/{token}/analyze")
    assert response.status_code == 200
    assert response.json()["status"] == "analyzing"
