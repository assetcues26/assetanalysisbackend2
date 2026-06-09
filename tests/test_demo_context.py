"""Unit tests for V6 demo context and climate mapping."""

from datetime import date

import pytest
from pydantic import ValidationError

from app.models.demo_context import DemoContext, infer_location_profile


def test_demo_context_valid():
    ctx = DemoContext(
        catalog_id="ac-001",
        asset_name="Micromax Split AC",
        description="Test",
        make="Micromax",
        model="IN1630V3Q",
        category="HVAC",
        subcategory="Split AC",
        acquisition_date=date(2021, 6, 15),
        original_cost_inr=33490,
        book_nbv_inr=22933.0,
        location="Mumbai, Maharashtra",
        asset_tag_number="100301912005536",
    )
    assert ctx.catalog_id == "ac-001"
    assert ctx.book_nbv_inr == 22933


def test_demo_context_requires_name_and_location():
    with pytest.raises(ValidationError):
        DemoContext(
            catalog_id="x",
            asset_name="  ",
            acquisition_date=date(2020, 1, 1),
            original_cost_inr=1000,
            book_nbv_inr=500,
            location="Delhi",
        )


@pytest.mark.parametrize(
    "location,expected",
    [
        ("Mumbai, Maharashtra", "coastal_humid"),
        ("Chennai, Tamil Nadu", "coastal_humid"),
        ("Delhi, NCR", "dry_hot_dust"),
        ("Jaipur, Rajasthan", "dry_hot_dust"),
        ("Bengaluru, Karnataka", "moderate"),
        ("Kolkata, West Bengal", "humid_inland"),
    ],
)
def test_infer_location_profile(location, expected):
    assert infer_location_profile(location) == expected


def test_build_demo_verification_tag_match():
    from app.models.demo_context import DemoContext
    from app.models.responses import Identifiers, LLMAnalysisResult
    from app.services.demo_analyzer import build_demo_verification

    ctx = DemoContext(
        catalog_id="ac-001",
        asset_name="Micromax Split AC",
        make="Micromax",
        model="IN1630V3Q",
        category="HVAC",
        subcategory="Split AC",
        acquisition_date=date(2021, 6, 15),
        original_cost_inr=33490,
        book_nbv_inr=22933.0,
        location="Mumbai, Maharashtra",
        asset_tag_number="100301912005536",
    )
    llm = LLMAnalysisResult(brand="Micromax", model="IN1630V3Q")
    ids = Identifiers(
        asset_tag_number="100301912005536",
        asset_tag_number_raw="100301912005536",
        tag_readable=True,
    )
    ok = build_demo_verification(ctx, llm, ids)
    assert ok.tag_number_match is True
    assert ok.make_match is True
    assert ok.model_match is True


def test_format_age_years_months():
    from app.utils.age_display import format_age_years_months

    assert format_age_years_months(5.242984257357974) == "5 years 3 months"
    assert format_age_years_months(1.0) == "1 year"
    assert format_age_years_months(0.5) == "6 months"


def test_build_demo_verification_tag_missing():
    from app.models.demo_context import DemoContext
    from app.models.responses import Identifiers, LLMAnalysisResult
    from app.services.demo_analyzer import build_demo_verification

    ctx = DemoContext(
        catalog_id="x",
        asset_name="Test",
        acquisition_date=date(2020, 1, 1),
        original_cost_inr=1000,
        book_nbv_inr=500,
        location="Delhi",
        asset_tag_number="1234567890123456",
    )
    llm = LLMAnalysisResult()
    ids = Identifiers()
    result = build_demo_verification(ctx, llm, ids)
    assert result.tag_number_match is False
    assert "not detected" in (result.tag_match_note or "").lower()
