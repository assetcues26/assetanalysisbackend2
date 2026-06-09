"""Tests for V6 post-LLM ERP validation engine."""

from datetime import date

from app.models.demo_context import DemoContext
from app.models.responses import (
    AssetDetails,
    BarcodeDetails,
    ConditionReport,
    DamageItem,
    DemoVerification,
    Identifiers,
    LLMAnalysisResult,
    LLMReasoningTrace,
    MoneyRange,
    NbvEstimate,
    PlacementInfo,
    Valuation,
    ValuationAmount,
)
from app.services.erp_validation_engine import enrich_demo_verification


def _ctx(**overrides):
    base = dict(
        catalog_id="ac-001",
        asset_name="Micromax Split AC",
        make="Micromax",
        model="IN1630V3Q",
        category="HVAC",
        subcategory="Split AC",
        acquisition_date=date(2021, 6, 15),
        original_cost_inr=33490,
        book_nbv_inr=22933,
        location="Mumbai, Maharashtra",
        asset_tag_number="100301912005536",
    )
    base.update(overrides)
    return DemoContext(**base)


def _base_verification() -> DemoVerification:
    return DemoVerification(
        erp_tag_number="100301912005536",
        detected_tag_number="100301912005536",
        tag_number_match=True,
        tag_match_note="match",
        location="Mumbai, Maharashtra",
        location_profile="coastal_humid",
        climate_valuation_points=["Coastal note."],
    )


def test_photo_coverage_score_from_angle_flags():
    llm = LLMAnalysisResult(
        reasoning=LLMReasoningTrace(
            uncertainty_flags=[
                "angle_missing_front",
                "angle_missing_tag_closeup",
            ]
        )
    )
    result = enrich_demo_verification(
        _ctx(),
        llm,
        Identifiers(),
        ConditionReport(),
        AssetDetails(category="HVAC"),
        Valuation(),
        _base_verification(),
    )
    assert result.photo_coverage_score == 3
    assert len(result.photo_angles) == 4
    assert result.photo_angles[0].id == "front"
    assert result.photo_angles[0].satisfied is False
    assert result.photo_angles[2].satisfied is True


def test_category_match():
    llm = LLMAnalysisResult(category="HVAC")
    asset = AssetDetails(category="HVAC")
    result = enrich_demo_verification(
        _ctx(),
        llm,
        Identifiers(),
        ConditionReport(),
        asset,
        Valuation(),
        _base_verification(),
    )
    assert result.category_match is True

    asset_mismatch = AssetDetails(category="Furniture")
    result2 = enrich_demo_verification(
        _ctx(),
        llm,
        Identifiers(),
        ConditionReport(),
        asset_mismatch,
        Valuation(),
        _base_verification(),
    )
    assert result2.category_match is False
    assert "category_mismatch" in result2.validation_warnings


def test_tag_readable_without_digits_suggests_review():
    ids = Identifiers(tag_readable=True, barcode=BarcodeDetails(present=True))
    result = enrich_demo_verification(
        _ctx(),
        LLMAnalysisResult(),
        ids,
        ConditionReport(),
        AssetDetails(),
        Valuation(),
        _base_verification(),
    )
    assert result.suggests_review is True
    assert "tag_readable_without_normalized_digits" in result.validation_warnings


def test_rust_corrosion_noted_from_damage():
    condition = ConditionReport(
        has_damage=True,
        damage_items=[
            DamageItem(type="rust", location="outdoor condenser", detail="fin corrosion")
        ],
    )
    result = enrich_demo_verification(
        _ctx(),
        LLMAnalysisResult(),
        Identifiers(),
        condition,
        AssetDetails(),
        Valuation(),
        _base_verification(),
    )
    assert result.rust_corrosion_noted is True


def test_tag_zoom_hint_from_barcode_placement():
    ids = Identifiers(
        barcode=BarcodeDetails(
            present=True,
            placement=PlacementInfo(
                seen_in_image=2,
                in_frame_position="lower-right",
            ),
        )
    )
    result = enrich_demo_verification(
        _ctx(),
        LLMAnalysisResult(barcode_seen_in_image=2),
        ids,
        ConditionReport(),
        AssetDetails(),
        Valuation(),
        _base_verification(),
    )
    assert result.tag_zoom_hint is not None
    assert result.tag_zoom_hint.image_index == 2


def test_nbv_vs_market_points():
    valuation = Valuation(
        as_is=ValuationAmount(
            inr=MoneyRange(min=10000, max=12000),
        ),
        nbv=NbvEstimate(
            inr=MoneyRange(min=14000, max=15000),
            method="erp_book_nbv",
        ),
    )
    result = enrich_demo_verification(
        _ctx(),
        LLMAnalysisResult(),
        Identifiers(),
        ConditionReport(),
        AssetDetails(),
        valuation,
        _base_verification(),
    )
    assert result.nbv_vs_market_points
    joined = " ".join(result.nbv_vs_market_points).lower()
    assert "book nbv" in joined or "below" in joined
