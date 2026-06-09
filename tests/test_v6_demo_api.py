"""API tests for V6 demo endpoints."""

import json
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import create_app
from app.models.responses import TokenUsage
from app.services.fx import FxResult
from tests.conftest import make_test_image
from tests.test_api import _mock_llm


def _make_v6_client():
    return TestClient(create_app())


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("V6_DEMO_ENABLED", "true")
    get_settings.cache_clear()
    yield _make_v6_client()
    get_settings.cache_clear()


@pytest.fixture
def v6_disabled_client(monkeypatch):
    monkeypatch.setenv("V6_DEMO_ENABLED", "false")
    get_settings.cache_clear()
    yield _make_v6_client()
    get_settings.cache_clear()


def _demo_context_payload() -> dict:
    return {
        "catalog_id": "laptop-002",
        "asset_name": "Dell Latitude 5420 Laptop",
        "description": "ERP description override",
        "make": "Dell",
        "model": "Latitude 5420",
        "category": "IT Equipment",
        "subcategory": "Laptop",
        "acquisition_date": "2021-03-10",
        "original_cost_inr": 72000,
        "book_nbv_inr": 38500,
        "location": "Bengaluru, Karnataka",
        "asset_tag_number": "100301912005537",
    }


def test_v6_disabled_returns_404(v6_disabled_client):
    response = v6_disabled_client.get("/v6/demo/catalog")
    assert response.status_code == 404


def test_demo_catalog_endpoint(client):
    response = client.get("/v6/demo/catalog")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 6
    assert data[0]["catalog_id"] == "ac-001"


def test_demo_analyze_requires_context(client):
    imgs = [make_test_image((40, 80, 120))]
    files = [("images", ("img.jpg", imgs[0], "image/jpeg"))]
    response = client.post("/v6/demo/analyze/multi", files=files)
    assert response.status_code in (400, 422)


def test_demo_analyze_success_mocked(monkeypatch):
    monkeypatch.setenv("V6_DEMO_ENABLED", "true")
    get_settings.cache_clear()
    settings = Settings(gemini_api_key="fake-key", v6_demo_enabled=True)
    usage = TokenUsage(
        input_tokens=5000,
        output_tokens=1500,
        total_tokens=6500,
        image_tokens=2240,
        text_tokens=2760,
        images_sent_to_gemini=2,
        per_image_token_budget=1120,
        estimated_image_tokens=2240,
    )
    fx = FxResult(rate=95.0, source="fixed_rate", is_fallback=False, as_of=None)
    ctx = _demo_context_payload()

    with (
        patch("app.api.v6.demo.get_settings", return_value=settings),
        patch(
            "app.services.gemini_v6_demo.GeminiV6DemoService.analyze_images_with_context",
            new=AsyncMock(return_value=(_mock_llm(), usage)),
        ) as mock_analyze,
        patch("app.services.demo_analyzer.get_usd_to_inr", new=AsyncMock(return_value=fx)),
    ):
        client = _make_v6_client()
        imgs = [make_test_image((i * 30, 70, 110)) for i in range(2)]
        files = [("images", (f"img{i}.jpg", img, "image/jpeg")) for i, img in enumerate(imgs)]
        response = client.post(
            "/v6/demo/analyze/multi",
            files=files,
            data={"demo_context": json.dumps(ctx), "locale": "en-IN"},
        )

    get_settings.cache_clear()
    assert response.status_code == 200, response.text
    mock_analyze.assert_awaited_once()
    data = response.json()

    assert data["status"] == "success"
    assert data["prompt_version"] == "v6-demo"
    assert data["analysis_method"] == "multi_image"
    assert data["images_analyzed"] == 2

    asset = data["asset"]
    assert asset["name"] == "Dell Latitude 5420 laptop"
    assert asset["description"]
    assert asset["brand"] == ctx["make"]
    assert asset["model"] == ctx["model"]
    assert asset["category"] == ctx["category"]
    assert asset["type"] == ctx["subcategory"]
    assert asset["asset_tag_number"] == "1234567890123456"

    verify = data["demo_verification"]
    assert verify is not None
    assert verify["tag_number_match"] is False
    assert verify["erp_tag_number"] == "100301912005537"
    assert verify["detected_tag_number"] == "1234567890123456"
    assert "photo_coverage_score" in verify
    assert verify["photo_coverage_score"] >= 1
    assert isinstance(verify.get("photo_angles"), list)
    assert "validation_warnings" in verify
    assert verify.get("tag_zoom_hint") is not None or verify.get("tag_visible") is not None

    nbv = data["valuation"]["nbv"]
    assert nbv is not None
    assert nbv["method"] == "erp_book_nbv"
    book = ctx["book_nbv_inr"]
    assert nbv["inr"]["min"] == pytest.approx(book, rel=1e-3)
    assert nbv["inr"]["max"] == pytest.approx(book, rel=1e-3)
    assert verify["erp_book_nbv_inr"] == pytest.approx(book, rel=1e-3)


def test_demo_analyze_allows_up_to_max_images_not_latency_cap(monkeypatch):
    """V6 should allow MAX_IMAGES (10), not the v1 latency cap (6)."""
    monkeypatch.setenv("V6_DEMO_ENABLED", "true")
    get_settings.cache_clear()
    settings = Settings(
        gemini_api_key="fake-key",
        max_images=10,
        max_images_latency_mode=6,
        v6_demo_enabled=True,
    )
    ctx = _demo_context_payload()

    with patch("app.api.v6.demo.get_settings", return_value=settings):
        client = _make_v6_client()
        imgs = [make_test_image((i * 10, 70, 110)) for i in range(7)]
        files = [("images", (f"img{i}.jpg", img, "image/jpeg")) for i, img in enumerate(imgs)]
        with patch(
            "app.services.gemini_v6_demo.GeminiV6DemoService.analyze_images_with_context",
            new=AsyncMock(return_value=(_mock_llm(), TokenUsage())),
        ):
            with patch(
                "app.services.demo_analyzer.get_usd_to_inr",
                new=AsyncMock(
                    return_value=FxResult(
                        rate=95.0, source="fixed_rate", is_fallback=False, as_of=None
                    )
                ),
            ):
                response = client.post(
                    "/v6/demo/analyze/multi",
                    files=files,
                    data={"demo_context": json.dumps(ctx), "locale": "en-IN"},
                )

    get_settings.cache_clear()
    assert response.status_code == 200, response.text


def test_demo_analyze_rejects_over_max_images(monkeypatch):
    monkeypatch.setenv("V6_DEMO_ENABLED", "true")
    get_settings.cache_clear()
    settings = Settings(gemini_api_key="fake-key", max_images=10, v6_demo_enabled=True)
    ctx = _demo_context_payload()

    with patch("app.api.v6.demo.get_settings", return_value=settings):
        client = _make_v6_client()
        imgs = [make_test_image((i * 5, 70, 110)) for i in range(11)]
        files = [("images", (f"img{i}.jpg", img, "image/jpeg")) for i, img in enumerate(imgs)]
        response = client.post(
            "/v6/demo/analyze/multi",
            files=files,
            data={"demo_context": json.dumps(ctx), "locale": "en-IN"},
        )

    get_settings.cache_clear()
    assert response.status_code == 400
    assert "At most 10 images allowed" in response.json()["detail"]
