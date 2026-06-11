"""API integration tests for the two analysis endpoints."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models.responses import (
    LLMAnalysisResult,
    LLMIdentityCandidate,
    LLMReasoningTrace,
    LLMStickerItem,
    LLMValuationInputs,
    TokenUsage,
)
from app.services.fx import FxResult
from tests.conftest import make_test_image


@pytest.fixture
def client():
    return TestClient(create_app())


def _mock_llm() -> LLMAnalysisResult:
    return LLMAnalysisResult(
        reasoning=LLMReasoningTrace(
            identity_candidates=[
                LLMIdentityCandidate(
                    label="Dell Latitude 5420",
                    visual_cues_for=["Dell logo", "Latitude 5420 nameplate"],
                    visual_cues_against=[],
                    confidence=0.92,
                ),
                LLMIdentityCandidate(
                    label="Dell Latitude 5410",
                    visual_cues_for=["Similar chassis"],
                    visual_cues_against=["Nameplate reads 5420"],
                    confidence=0.4,
                ),
            ],
            selected_identity_rationale="Nameplate and palm-rest sticker read Latitude 5420.",
            uncertainty_flags=[],
            damage_notes="Scuffs on lid and palm rest scratch.",
            repair_judgement_notes="IT equipment — cosmetic lid scuffs only.",
        ),
        valuation_inputs=LLMValuationInputs(
            market_segment="it_equipment",
            reference_like_new_usd=900,
            condition_adjustment_pct=-12,
            age_years_min=3,
            age_years_max=4,
            valuation_rationale="Business laptop, moderate cosmetic wear.",
        ),
        asset_name="Dell Latitude 5420 laptop",
        category="Laptop",
        asset_type="Business ultrabook",
        brand="Dell",
        model="Latitude 5420",
        color="Black",
        material="Aluminium and plastic",
        estimated_dimensions="~32 x 21 x 2 cm",
        estimated_age="~2021, 3-4 years",
        quantity=1,
        specifications=["Intel Core i7", "16GB RAM"],
        accessories=["power adapter"],
        distinguishing_features=["Dell logo on lid"],
        description="Black 14-inch business laptop, aluminium lid.",
        condition_summary="Fair. Scuffs on lid, scratch on palm rest.",
        condition_grade="Fair",
        condition_score=62,
        cosmetic_condition="Visible scuffs on the lid; palm rest lightly scratched.",
        structural_condition="Frame solid, hinges firm, no cracks.",
        functional_status="Appears functional",
        cleanliness="Lightly soiled",
        wear_level="Moderate",
        usability="Usable, minor repair advised",
        repair_recommendation="Buff lid, clean chassis.",
        estimated_remaining_life="2-4 years with normal use",
        missing_parts=[],
        functional_issues=["bent hinge restricts opening"],
        positive_aspects=["screen intact", "all keys present"],
        damage_items=[
            {
                "location": "Top lid rear-left",
                "type": "dent",
                "severity": "moderate",
                "seen_in_image": 2,
                "horizontal": "left",
                "in_frame_position": "upper-left",
                "detail": "A ~1cm dent on the rear-left corner of the lid.",
                "affects_function": False,
                "repair_action": "Reshape or replace lid panel.",
                "repair_needed": "recommended",
                "repair_urgency": "scheduled",
                "acceptable_wear": False,
            },
            {
                "location": "Palm rest",
                "type": "scratch",
                "severity": "minor",
                "seen_in_image": 1,
                "horizontal": "center",
                "repair_needed": "cosmetic_only",
                "repair_urgency": "none",
                "acceptable_wear": False,
            },
        ],
        asset_tag_number="1234567890123456",
        tag_readable=True,
        tag_detection_reasoning="Tag on base, Image 3. 16 digits.",
        barcode_present=True,
        barcode_asset_location="base panel",
        barcode_horizontal="right",
        barcode_seen_in_image=3,
        barcode_position="Base panel, Image 3",
        stickers=[
            LLMStickerItem(
                label_text="Dell",
                sticker_type="brand",
                asset_location="lid",
                horizontal="center",
                seen_in_image=1,
            ),
            LLMStickerItem(
                label_text="Latitude 5420",
                sticker_type="spec",
                asset_location="palm rest",
                horizontal="left",
                seen_in_image=1,
            ),
        ],
        visible_labels=["Dell", "Latitude 5420"],
        confidence_asset_name=0.9,
        confidence_asset_condition=0.8,
        confidence_asset_description=0.85,
        confidence_asset_tag_number=0.7,
        estimated_value_usd_min=120,
        estimated_value_usd_max=180,
        like_new_value_usd_min=260,
        like_new_value_usd_max=320,
        valuation_confidence=0.45,
        valuation_assumptions="2021 model, used, moderate wear.",
    )


def test_health_endpoint(client):
    response = client.get("/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_analyze_requires_image(client):
    response = client.post("/v1/assets/analyze/multi", data={})
    assert response.status_code in (400, 422)


@pytest.mark.parametrize(
    "path,method",
    [
        ("/v1/assets/analyze/collage", "collage"),
        ("/v1/assets/analyze/multi", "multi_image"),
    ],
)
def test_analyze_success_mocked(path, method):
    settings = Settings(gemini_api_key="fake-key")
    usage = TokenUsage(
        input_tokens=8000,
        output_tokens=2000,
        total_tokens=10000,
        image_tokens=6720,
        text_tokens=1280,
        images_sent_to_gemini=3,
        per_image_token_budget=1120,
        estimated_image_tokens=3360,
    )
    fx = FxResult(rate=100.0, source="fixed_rate", is_fallback=False, as_of=None)

    with (
        patch("app.api.v1.assets.get_settings", return_value=settings),
        patch(
            "app.services.gemini.GeminiService.analyze_images",
            new=AsyncMock(return_value=(_mock_llm(), usage)),
        ) as mock_analyze,
        patch("app.services.analyzer.get_usd_to_inr", new=AsyncMock(return_value=fx)),
    ):
        client = TestClient(create_app())
        imgs = [make_test_image((i * 20, 60, 120)) for i in range(3)]
        files = [("images", (f"img{i}.jpg", img, "image/jpeg")) for i, img in enumerate(imgs)]
        response = client.post(path, files=files)

    assert response.status_code == 200, response.text
    mock_analyze.assert_awaited_once()
    data = response.json()

    assert data["status"] == "success"
    assert data["analysis_method"] == method
    assert data["images_analyzed"] == 3

    # collage endpoint returns the merged image as a base64 data URL (first field);
    # multi endpoint has no collage.
    if method == "collage":
        assert list(data.keys())[0] == "collage_base64"
        assert data["collage_base64"].startswith("data:image/jpeg;base64,")
    else:
        assert data["collage_base64"] is None

    asset = data["asset"]
    assert asset["name"] == "Dell Latitude 5420 laptop"
    assert asset["category"] == "Laptop"
    assert asset["brand"] == "Dell"
    assert asset["specifications"] == ["Intel Core i7", "16GB RAM"]
    assert asset["accessories"] == ["power adapter"]
    assert asset["asset_tag_number"] == "1234567890123456"
    assert asset["quantity"] == 1

    cond = data["condition"]
    assert cond["grade"] == "Fair"
    assert cond["overall_score"] == 62
    assert cond["functional_status"] == "Appears functional"
    assert cond["cosmetic_condition"]
    assert cond["structural_condition"]
    assert cond["cleanliness"] == "Lightly soiled"
    assert cond["wear_level"] == "Moderate"
    assert cond["usability"] == "Usable, minor repair advised"
    assert cond["repair_recommendation"]
    assert cond["estimated_remaining_life"] == "2-4 years with normal use"
    assert cond["functional_issues"] == ["bent hinge restricts opening"]
    assert cond["positive_aspects"] == ["screen intact", "all keys present"]
    assert cond["has_damage"] is True
    assert cond["damage_count"] == 2
    assert cond["damage_by_severity"] == {"minor": 1, "moderate": 1, "severe": 0}
    assert cond["damage_items"][0]["severity"] == "moderate"
    assert cond["damage_items"][0]["detail"]
    assert cond["damage_items"][0]["affects_function"] is False
    assert cond["damage_items"][0]["repair_action"] == "Reshape or replace lid panel."
    assert cond["damage_items"][0]["placement"]["seen_in_image"] == 2
    assert cond["damage_items"][0]["placement"]["horizontal"] == "left"

    ids = data["identifiers"]
    assert ids["asset_tag_number"] == "1234567890123456"
    assert ids["asset_tag_number_raw"] == "1234567890123456"
    assert ids["tag_readable"] is True
    assert ids["tag_position"] == "Base panel, Image 3"
    assert "Dell" in ids["visible_labels"]
    assert "Latitude 5420" in ids["visible_labels"]
    assert "Intel Core i7" in ids["visible_labels"]
    assert len(ids["stickers"]) >= 4
    assert ids["barcode"]["present"] is True
    assert ids["barcode"]["placement"]["seen_in_image"] == 3

    assert data["prompt_version"] == "v2"
    policy = data["analysis_policy"]
    assert policy["valuation_confidence_threshold"] == settings.valuation_confidence_threshold
    assert policy["reference_prices_source"] == "reference_prices_IN.json"
    assert policy["market_region"] == "IN"
    assert policy["display_currency"] == "INR"
    assert data["reasoning_summary"]["selected_identity_rationale"]
    assert len(data["reasoning_summary"]["identity_candidates"]) >= 1
    assert "stage_timings_ms" in data

    val = data["valuation"]
    assert val["status"] in ("ok", "indicative_only")
    assert val["as_is"]["inr"]["min"] is not None
    assert val["as_is"]["inr"]["max"] is not None
    assert val["like_new_reference"]["inr"]["max"] is not None
    assert val["as_is"]["inr"]["max"] <= val["like_new_reference"]["inr"]["max"]
    assert val["as_is"]["usd"]["min"] is None
    assert val["as_is"]["usd"]["max"] is None
    assert val.get("nbv") is not None
    assert "nbv_exceeds_as_is" in val
    assert val["nbv_exceeds_as_is"] in (True, False)
    assert val.get("nbv_vs_as_is_note")

    assert data["condition"]["repair_plan"] is not None
    assert data["condition"]["repair_plan"]["items"]

    conf = data["confidence"]
    assert conf["asset_name"] == 0.9
    assert conf["overall"] == round((0.9 + 0.8 + 0.85 + 0.7) / 4, 3)

    usage_out = data["token_usage"]
    assert usage_out["input_tokens"] == 8000
    assert usage_out["image_tokens"] == 6720
    assert usage_out["text_tokens"] == 1280
    assert usage_out["image_tokens"] + usage_out["text_tokens"] == usage_out["input_tokens"]
    assert usage_out["per_image_token_budget"] == 1120

    cost = data["cost"]
    assert cost["model"] == settings.gemini_model
    assert cost["usd_to_inr"] == 100.0
    assert cost["total_cost_usd"] == pytest.approx(
        8000 / 1e6 * settings.gemini_input_usd_per_1m
        + 2000 / 1e6 * settings.gemini_output_usd_per_1m,
        rel=1e-6,
    )
    assert cost["total_cost_inr"] == pytest.approx(cost["total_cost_usd"] * 100.0, rel=1e-6)
    assert cost["fx_source"] == "fixed_rate"


def test_analyze_us_market_region():
    settings = Settings(gemini_api_key="fake-key")
    usage = TokenUsage(
        input_tokens=8000,
        output_tokens=2000,
        total_tokens=10000,
        image_tokens=6720,
        text_tokens=1280,
        images_sent_to_gemini=1,
        per_image_token_budget=1120,
        estimated_image_tokens=1120,
    )
    fx = FxResult(rate=1.0, source="fixed_rate", is_fallback=False, as_of=None)

    with (
        patch("app.api.v1.assets.get_settings", return_value=settings),
        patch(
            "app.services.gemini.GeminiService.analyze_images",
            new=AsyncMock(return_value=(_mock_llm(), usage)),
        ),
        patch("app.services.analyzer.get_fx_rate", new=AsyncMock(return_value=fx)),
        patch("app.services.analyzer.get_usd_to_inr", new=AsyncMock(return_value=fx)),
    ):
        client = TestClient(create_app())
        imgs = [make_test_image((40, 80, 140))]
        files = [("images", ("img0.jpg", imgs[0], "image/jpeg"))]
        response = client.post(
            "/v1/assets/analyze/multi",
            files=files,
            data={"market_region": "US"},
        )

    assert response.status_code == 200, response.text
    data = response.json()
    policy = data["analysis_policy"]
    assert policy["market_region"] == "US"
    assert policy["display_currency"] == "USD"
    assert policy["reference_prices_source"] == "reference_prices_US.json"

    val = data["valuation"]
    assert val["as_is"]["display_currency"] == "USD"
    assert val["as_is"]["display"]["min"] is not None
    assert val["as_is"]["inr"]["min"] is None
