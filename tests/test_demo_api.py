"""API tests for /v1/demo routes."""

from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from app.api.v1.demo import get_repo
from app.config import Settings, get_settings
from app.main import create_app
from app.models.demo import ClearDemoDataResponse


def test_clear_demo_data_success():
    settings = Settings(
        supabase_persist_enabled=True,
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="test-key",
        demo_user_id=100,
    )
    mock_repo = MagicMock()
    mock_repo.enabled = True
    mock_repo.clear_demo_data = AsyncMock(
        return_value=ClearDemoDataResponse(
            analyses_deleted=3,
            sessions_deleted=1,
            storage_objects_removed=12,
        )
    )

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_repo] = lambda: mock_repo
    client = TestClient(app)

    response = client.post("/v1/demo/clear-data")
    assert response.status_code == 200
    body = response.json()
    assert body["analyses_deleted"] == 3
    assert body["sessions_deleted"] == 1
    assert body["cleared"] is True


def test_clear_demo_data_disabled_returns_503():
    settings = Settings(supabase_persist_enabled=False)
    mock_repo = MagicMock()
    mock_repo.enabled = False

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_repo] = lambda: mock_repo
    client = TestClient(app)

    response = client.post("/v1/demo/clear-data")
    assert response.status_code == 503
