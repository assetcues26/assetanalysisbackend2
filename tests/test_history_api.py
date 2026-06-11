"""API tests for /v1/history routes."""

import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.api.v1.history import get_repo
from app.config import Settings, get_settings
from app.main import create_app
from app.models.history import HistoryListItem


@pytest.fixture
def client():
    return TestClient(create_app())


@pytest.fixture
def persist_settings():
    return Settings(
        supabase_persist_enabled=True,
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="test-key",
        demo_user_id=100,
    )


def test_history_disabled_returns_503():
    disabled_settings = Settings(supabase_persist_enabled=False)
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: disabled_settings
    test_client = TestClient(app)
    response = test_client.get("/v1/history")
    assert response.status_code == 503


def test_history_requires_valid_uuid_for_detail(client, persist_settings):
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: persist_settings
    mock_repo = AsyncMock()
    mock_repo.enabled = True
    app.dependency_overrides[get_repo] = lambda: mock_repo

    test_client = TestClient(app)
    response = test_client.get("/v1/history/not-valid")
    assert response.status_code == 400


def test_history_list_success(persist_settings):
    items = [
        HistoryListItem(
            entry_id=str(uuid.uuid4()),
            request_id=str(uuid.uuid4()),
            asset_name="Compressor",
            processed_at="2026-01-01T00:00:00Z",
        )
    ]
    mock_repo = AsyncMock()
    mock_repo.enabled = True
    mock_repo.list_analyses = AsyncMock(return_value=(items, 1))

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: persist_settings
    app.dependency_overrides[get_repo] = lambda: mock_repo
    test_client = TestClient(app)

    response = test_client.get("/v1/history")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1


def test_history_detail_not_found(persist_settings):
    mock_repo = AsyncMock()
    mock_repo.enabled = True
    mock_repo.get_analysis = AsyncMock(return_value=None)
    entry_id = str(uuid.uuid4())

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: persist_settings
    app.dependency_overrides[get_repo] = lambda: mock_repo
    test_client = TestClient(app)

    response = test_client.get(f"/v1/history/{entry_id}")
    assert response.status_code == 404


def test_history_delete_success(persist_settings):
    mock_repo = AsyncMock()
    mock_repo.enabled = True
    mock_repo.delete_analysis = AsyncMock(return_value=True)
    entry_id = str(uuid.uuid4())

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: persist_settings
    app.dependency_overrides[get_repo] = lambda: mock_repo
    test_client = TestClient(app)

    response = test_client.delete(f"/v1/history/{entry_id}")
    assert response.status_code == 200
    assert response.json()["deleted"] is True


def test_demo_api_key_rejected(persist_settings):
    persist_settings.demo_api_key = "secret-demo-key"
    mock_repo = AsyncMock()
    mock_repo.enabled = True

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: persist_settings
    app.dependency_overrides[get_repo] = lambda: mock_repo
    test_client = TestClient(app)

    response = test_client.get("/v1/history", headers={"X-Demo-Key": "wrong"})
    assert response.status_code == 401
