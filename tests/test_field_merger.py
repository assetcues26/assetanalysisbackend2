"""Tests for field normalization and asset-detail mapping."""

from app.models.responses import LLMAnalysisResult
from app.services.field_merger import _clean_list, normalize_tag_number, to_asset_details


def test_normalize_tag_number_valid():
    assert normalize_tag_number("100301912005536") == "100301912005536"


def test_normalize_tag_number_unreadable():
    assert normalize_tag_number("UNREADABLE") is None
    assert normalize_tag_number("123") is None  # too short
    assert normalize_tag_number(None) is None


def test_clean_list_dedupes_and_trims():
    assert _clean_list(["  Intel i7 ", "Intel i7", "16GB", ""]) == ["Intel i7", "16GB"]


def test_to_asset_details_maps_rich_fields():
    llm = LLMAnalysisResult(
        asset_name="Dell Latitude 5420 laptop",
        category="Laptop",
        asset_type="Business ultrabook",
        brand="Dell",
        model="Latitude 5420",
        color="Black",
        material="Aluminium",
        quantity=1,
        specifications=["Intel i7", "16GB RAM"],
        accessories=["charger"],
        distinguishing_features=["Dell logo on lid"],
        description="Black 14-inch laptop.",
        asset_tag_number="1234567890123456",
    )
    asset = to_asset_details(llm)
    assert asset.name == "Dell Latitude 5420 laptop"
    assert asset.category == "Laptop"
    assert asset.type == "Business ultrabook"
    assert asset.brand == "Dell"
    assert asset.specifications == ["Intel i7", "16GB RAM"]
    assert asset.asset_tag_number == "1234567890123456"


def test_to_asset_details_normalizes_unreadable_tag_and_quantity():
    llm = LLMAnalysisResult(
        asset_name="Office chair",
        asset_tag_number="UNREADABLE",
        quantity=0,
    )
    asset = to_asset_details(llm)
    assert asset.name == "Office chair"
    assert asset.asset_tag_number is None
    assert asset.quantity == 1  # invalid quantity falls back to 1
    assert asset.estimated_model_years is None
    assert asset.estimated_age_years is None


def test_to_asset_details_estimated_age_unknown_when_null():
    asset = to_asset_details(LLMAnalysisResult(asset_name="AC unit"))
    assert asset.estimated_model_years is None
    assert asset.estimated_age_years is None
    assert asset.quantity == 1


def test_to_asset_details_splits_model_year_and_age():
    llm = LLMAnalysisResult(
        asset_name="Printer",
        estimated_model_year_min=2020,
        estimated_model_year_max=2021,
    )
    asset = to_asset_details(llm)
    assert asset.estimated_model_years == "2020–2021"
    assert "as of" in (asset.estimated_age_years or "")
