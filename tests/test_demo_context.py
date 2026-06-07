"""Unit tests for V6 demo context and climate mapping."""

from datetime import date

import pytest
from pydantic import ValidationError

from app.models.demo_context import DemoContext, infer_location_profile


def test_demo_context_valid():
    ctx = DemoContext(
        catalog_id="demo-ac-001",
        asset_name="Micromax Split AC",
        description="Test",
        make="Micromax",
        model="IN1630V3Q",
        category="HVAC",
        subcategory="Split AC",
        acquisition_date=date(2019, 6, 15),
        original_cost_inr=28500,
        book_nbv_inr=14200,
        location="Mumbai, Maharashtra",
        asset_tag_number="100301912005536",
    )
    assert ctx.catalog_id == "demo-ac-001"
    assert ctx.book_nbv_inr == 14200


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
