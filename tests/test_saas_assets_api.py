"""API tests for /v1/saas routes."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.v1.saas_assets import get_repo
from app.config import Settings, get_settings
from app.main import create_app
from app.models.saas_assets import (
    AssetCreateSessionDetail,
    CompleteAssetSessionResponse,
    SaasAssetDetailResponse,
    SaasAssetSummary,
)
from app.services.saas_assets_repository import SessionCompletedError, validate_create_metadata


@pytest.fixture
def saas_settings():
    return Settings(
        supabase_persist_enabled=True,
        saas_assets_enabled=True,
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="test-key",
        demo_user_id=100,
    )


TEST_ASSET_ID = "a39b8e4a-3d87-48a9-aae0-cb24c7aa99cb"


def _asset_summary(
    asset_id: str = TEST_ASSET_ID,
    ai_status: str = "pending",
    asset_image_url: str | None = None,
) -> SaasAssetSummary:
    return SaasAssetSummary(
        id=asset_id,
        assetid="AST-10001",
        assetname="Dell Latitude",
        tagnumber="TAG-1",
        company="Tech Co",
        cost=125000.5,
        acquisitiondate="15-08-2023",
        ai_status=ai_status,
        asset_image_url=asset_image_url,
    )


def test_saas_disabled_returns_503():
    disabled = Settings(supabase_persist_enabled=False, saas_assets_enabled=False)
    mock_repo = MagicMock()
    mock_repo.enabled = False

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: disabled
    app.dependency_overrides[get_repo] = lambda: mock_repo
    client = TestClient(app)

    response = client.get("/v1/saas/assets")
    assert response.status_code == 503


def test_list_assets_success(saas_settings):
    mock_repo = MagicMock()
    mock_repo.enabled = True
    mock_repo.list_assets = AsyncMock(return_value=([_asset_summary()], 1))

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: saas_settings
    app.dependency_overrides[get_repo] = lambda: mock_repo
    client = TestClient(app)

    response = client.get("/v1/saas/assets")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["assetid"] == "AST-10001"


def test_create_asset_session_success(saas_settings):
    mock_repo = MagicMock()
    mock_repo.enabled = True
    mock_repo.create_asset_session = AsyncMock(
        return_value=AssetCreateSessionDetail(
            session_token="tok" + "a" * 30,
            status="active",
            draft_json={"assetname": "Test"},
            expires_at="2026-12-31T00:00:00Z",
        )
    )

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: saas_settings
    app.dependency_overrides[get_repo] = lambda: mock_repo
    client = TestClient(app)

    response = client.post("/v1/saas/asset-sessions", json={"draft_json": {"assetname": "Test"}})
    assert response.status_code == 200
    assert response.json()["session_token"].startswith("tok")


def test_get_session_completed_returns_410(saas_settings):
    mock_repo = MagicMock()
    mock_repo.enabled = True
    mock_repo.get_asset_session = AsyncMock(side_effect=SessionCompletedError("Session already used"))

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: saas_settings
    app.dependency_overrides[get_repo] = lambda: mock_repo
    client = TestClient(app)

    token = "a" * 32
    response = client.get(f"/v1/saas/asset-sessions/{token}")
    assert response.status_code == 410


def test_analyze_asset_triggers_background(saas_settings):
    mock_repo = MagicMock()
    mock_repo.enabled = True
    mock_repo.get_asset = AsyncMock(
        return_value=SaasAssetDetailResponse(
            asset=_asset_summary(asset_image_url="https://example.com/asset.jpg"),
            latest_analysis=None,
        )
    )
    mock_repo.set_ai_status = AsyncMock()

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: saas_settings
    app.dependency_overrides[get_repo] = lambda: mock_repo
    client = TestClient(app)

    with patch("app.api.v1.saas_assets._background_analyze", new_callable=AsyncMock):
        response = client.post(f"/v1/saas/assets/{TEST_ASSET_ID}/analyze")
    assert response.status_code == 200
    assert response.json()["ai_status"] == "analyzing"
    mock_repo.set_ai_status.assert_awaited_once()


def test_validate_create_metadata_required_fields():
    with pytest.raises(ValueError, match="Missing required fields"):
        validate_create_metadata({"assetname": "X"})


def test_validate_create_metadata_date_format():
    data = {k: "x" for k in (
        "assetname", "tagnumber", "assetnumber", "makemodelid", "makemodelname",
        "companyid", "company", "customerid", "assetclassname",
    )}
    data["cost"] = "100"
    data["acquisitiondate"] = "2023-08-15"
    data["_has_asset_image"] = True
    with pytest.raises(ValueError, match="DD-MM-YYYY"):
        validate_create_metadata(data)


def test_complete_session_success(saas_settings):
    mock_repo = MagicMock()
    mock_repo.enabled = True
    mock_repo.complete_asset_session = AsyncMock(
        return_value=CompleteAssetSessionResponse(
            asset_id="new-asset-id",
            assetid="AST-10002",
            ai_status="analyzing",
        )
    )

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: saas_settings
    app.dependency_overrides[get_repo] = lambda: mock_repo
    client = TestClient(app)

    token = "b" * 32
    with patch("app.api.v1.saas_assets._background_analyze", new_callable=AsyncMock):
        response = client.post(
            f"/v1/saas/asset-sessions/{token}/complete",
            data={
                "assetname": "HP Printer",
                "tagnumber": "100000078",
                "assetnumber": "FAR1001",
                "makemodelid": "MK01",
                "makemodelname": "HP Laptop",
                "companyid": "10001",
                "company": "Flipkart",
                "customerid": "10001",
                "assetclassname": "IT ASSET",
                "cost": "36000",
                "acquisitiondate": "01-01-2023",
            },
        )
    assert response.status_code == 200
    assert response.json()["assetid"] == "AST-10002"


def test_lookups_success(saas_settings):
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: saas_settings
    mock_repo = MagicMock()
    mock_repo.enabled = True
    app.dependency_overrides[get_repo] = lambda: mock_repo
    client = TestClient(app)

    response = client.get("/v1/saas/lookups?type=company")
    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "company"
    assert isinstance(body["items"], list)


def test_dashboard_stats_success(saas_settings):
    mock_repo = MagicMock()
    mock_repo.enabled = True
    mock_repo.get_dashboard_stats = AsyncMock(
        return_value={
            "total": 10,
            "pass_count": 5,
            "fail_count": 2,
            "pending": 1,
            "error": 1,
            "analyzing": 1,
        }
    )

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: saas_settings
    app.dependency_overrides[get_repo] = lambda: mock_repo
    client = TestClient(app)

    response = client.get("/v1/saas/assets/stats")
    assert response.status_code == 200
    assert response.json()["total"] == 10


def test_patch_asset_success(saas_settings):
    mock_repo = MagicMock()
    mock_repo.enabled = True
    mock_repo.update_asset = AsyncMock(
        return_value=_asset_summary().__class__(
            **_asset_summary().model_dump() | {"assetname": "Updated"}
        )
    )

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: saas_settings
    app.dependency_overrides[get_repo] = lambda: mock_repo
    client = TestClient(app)

    response = client.patch(
        f"/v1/saas/assets/{TEST_ASSET_ID}",
        json={"assetname": "Updated"},
    )
    assert response.status_code == 200
    assert response.json()["asset"]["assetname"] == "Updated"


def test_patch_asset_with_reanalyze(saas_settings):
    mock_repo = MagicMock()
    mock_repo.enabled = True
    mock_repo.update_asset = AsyncMock(
        return_value=_asset_summary().__class__(
            **_asset_summary().model_dump() | {"assetname": "Updated"}
        )
    )
    mock_repo.set_ai_status = AsyncMock()
    mock_repo.get_asset = AsyncMock(
        return_value=SaasAssetDetailResponse(
            asset=_asset_summary().__class__(
                **_asset_summary().model_dump() | {"assetname": "Updated", "ai_status": "analyzing"}
            ),
            latest_analysis=None,
        )
    )

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: saas_settings
    app.dependency_overrides[get_repo] = lambda: mock_repo
    client = TestClient(app)

    with patch("app.api.v1.saas_assets._background_analyze", new_callable=AsyncMock):
        response = client.patch(
            f"/v1/saas/assets/{TEST_ASSET_ID}?reanalyze=true",
            json={"assetname": "Updated"},
        )
    assert response.status_code == 200
    assert response.json()["asset"]["ai_status"] == "analyzing"
    mock_repo.set_ai_status.assert_awaited_once()


def test_delete_asset_success(saas_settings):
    mock_repo = MagicMock()
    mock_repo.enabled = True
    mock_repo.delete_asset = AsyncMock(return_value=True)

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: saas_settings
    app.dependency_overrides[get_repo] = lambda: mock_repo
    client = TestClient(app)

    response = client.delete(f"/v1/saas/assets/{TEST_ASSET_ID}")
    assert response.status_code == 204


def test_bulk_delete_success(saas_settings):
    mock_repo = MagicMock()
    mock_repo.enabled = True
    mock_repo.bulk_delete = AsyncMock(return_value=2)

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: saas_settings
    app.dependency_overrides[get_repo] = lambda: mock_repo
    client = TestClient(app)

    response = client.post(
        "/v1/saas/assets/bulk-delete",
        json={"asset_ids": ["a1", "a2"]},
    )
    assert response.status_code == 200
    assert response.json()["processed"] == 2


def test_save_draft_success(saas_settings):
    mock_repo = MagicMock()
    mock_repo.enabled = True
    mock_repo.save_web_draft = AsyncMock(
        return_value={
            "id": "draft-1",
            "title": "My draft",
            "draft_json": {"assetname": "Test"},
            "asset_image_url": None,
            "barcode_image_url": None,
            "updated_at": "2026-01-01T00:00:00Z",
        }
    )

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: saas_settings
    app.dependency_overrides[get_repo] = lambda: mock_repo
    client = TestClient(app)

    response = client.post(
        "/v1/saas/drafts",
        json={"title": "My draft", "draft_json": {"assetname": "Test"}},
    )
    assert response.status_code == 200
    assert response.json()["id"] == "draft-1"


def test_analyze_with_metadata_patch(saas_settings):
    mock_repo = MagicMock()
    mock_repo.enabled = True
    mock_repo.get_asset = AsyncMock(
        return_value=SaasAssetDetailResponse(
            asset=_asset_summary(asset_image_url="https://example.com/asset.jpg"),
            latest_analysis=None,
        )
    )
    mock_repo.set_ai_status = AsyncMock()

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: saas_settings
    app.dependency_overrides[get_repo] = lambda: mock_repo
    client = TestClient(app)

    with patch("app.api.v1.saas_assets._background_analyze", new_callable=AsyncMock) as bg:
        response = client.post(
            f"/v1/saas/assets/{TEST_ASSET_ID}/analyze",
            json={"metadata_patch": {"cost": "130000"}},
        )
    assert response.status_code == 200
    bg.assert_awaited_once()


def test_upload_asset_images_success(saas_settings):
    mock_repo = MagicMock()
    mock_repo.enabled = True
    mock_repo.get_asset = AsyncMock(
        return_value=SaasAssetDetailResponse(asset=_asset_summary(), latest_analysis=None)
    )
    mock_repo.update_asset = AsyncMock(return_value=_asset_summary(ai_status="analyzing"))
    mock_repo.log_activity = AsyncMock()
    mock_repo.set_ai_status = AsyncMock()
    mock_repo.get_asset.side_effect = [
        SaasAssetDetailResponse(asset=_asset_summary(), latest_analysis=None),
        SaasAssetDetailResponse(asset=_asset_summary(ai_status="analyzing"), latest_analysis=None),
    ]

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: saas_settings
    app.dependency_overrides[get_repo] = lambda: mock_repo
    client = TestClient(app)

    with patch("app.api.v1.saas_assets._background_analyze", new_callable=AsyncMock) as bg:
        response = client.post(
            f"/v1/saas/assets/{TEST_ASSET_ID}/images",
            files={"assetimage": ("asset.jpg", b"fake-image", "image/jpeg")},
        )

    assert response.status_code == 200
    assert response.json()["asset"]["ai_status"] == "analyzing"
    mock_repo.update_asset.assert_awaited_once()
    mock_repo.log_activity.assert_awaited_once()
    mock_repo.set_ai_status.assert_awaited_once()
    bg.assert_awaited_once()


def test_upload_asset_images_requires_asset_image_when_missing(saas_settings):
    mock_repo = MagicMock()
    mock_repo.enabled = True
    mock_repo.get_asset = AsyncMock(
        return_value=SaasAssetDetailResponse(asset=_asset_summary(), latest_analysis=None)
    )

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: saas_settings
    app.dependency_overrides[get_repo] = lambda: mock_repo
    client = TestClient(app)

    response = client.post(
        f"/v1/saas/assets/{TEST_ASSET_ID}/images",
        files={"barcodeimage": ("barcode.jpg", b"fake-image", "image/jpeg")},
    )
    assert response.status_code == 400
    assert "Asset image is required" in response.json()["detail"]


def test_upload_asset_images_from_session_token(saas_settings):
    mock_repo = MagicMock()
    mock_repo.enabled = True
    mock_repo.get_asset = AsyncMock(
        return_value=SaasAssetDetailResponse(asset=_asset_summary(), latest_analysis=None)
    )
    mock_repo.apply_session_images_to_asset = AsyncMock(
        return_value=_asset_summary(ai_status="analyzing")
    )
    mock_repo.log_activity = AsyncMock()
    mock_repo.set_ai_status = AsyncMock()
    mock_repo.get_asset.side_effect = [
        SaasAssetDetailResponse(asset=_asset_summary(), latest_analysis=None),
        SaasAssetDetailResponse(
            asset=_asset_summary(ai_status="analyzing"),
            latest_analysis=None,
        ),
    ]

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: saas_settings
    app.dependency_overrides[get_repo] = lambda: mock_repo
    client = TestClient(app)

    token = "a" * 32
    with patch("app.api.v1.saas_assets._background_analyze", new_callable=AsyncMock) as bg:
        response = client.post(
            f"/v1/saas/assets/{TEST_ASSET_ID}/images?session_token={token}",
        )

    assert response.status_code == 200
    mock_repo.apply_session_images_to_asset.assert_awaited_once()
    mock_repo.update_asset.assert_not_called()
    bg.assert_awaited_once()


def test_analyze_asset_requires_photos(saas_settings):
    mock_repo = MagicMock()
    mock_repo.enabled = True
    mock_repo.get_asset = AsyncMock(
        return_value=SaasAssetDetailResponse(asset=_asset_summary(), latest_analysis=None)
    )

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: saas_settings
    app.dependency_overrides[get_repo] = lambda: mock_repo
    client = TestClient(app)

    response = client.post(f"/v1/saas/assets/{TEST_ASSET_ID}/analyze")
    assert response.status_code == 400
    assert "Upload asset photos" in response.json()["detail"]


def test_delete_asset_image(saas_settings):
    mock_repo = MagicMock()
    mock_repo.enabled = True
    mock_repo.delete_asset_image = AsyncMock(
        return_value=_asset_summary(ai_status="pending")
    )

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: saas_settings
    app.dependency_overrides[get_repo] = lambda: mock_repo
    client = TestClient(app)

    response = client.delete(f"/v1/saas/assets/{TEST_ASSET_ID}/images?kind=asset")

    assert response.status_code == 200
    assert response.json()["asset"]["ai_status"] == "pending"
    mock_repo.delete_asset_image.assert_awaited_once_with(
        saas_settings.demo_user_id, TEST_ASSET_ID, "asset"
    )


def test_delete_asset_image_invalid_kind(saas_settings):
    mock_repo = MagicMock()
    mock_repo.enabled = True
    mock_repo.delete_asset_image = AsyncMock(side_effect=ValueError("image_kind must be asset or barcode"))

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: saas_settings
    app.dependency_overrides[get_repo] = lambda: mock_repo
    client = TestClient(app)

    response = client.delete(f"/v1/saas/assets/{TEST_ASSET_ID}/images?kind=invalid")

    assert response.status_code == 422
