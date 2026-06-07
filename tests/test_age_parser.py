"""Tests for age parsing."""

from app.models.responses import LLMAnalysisResult
from app.services.age_parser import (
    build_asset_age_display,
    parse_estimated_age,
    resolve_asset_age,
)


def test_parse_year_range_beats_years_phrase():
    result = parse_estimated_age("~3-4 years (approx. 2020-2021)", now_year=2026)
    assert result is not None
    assert result.years_min == 5
    assert result.years_max == 6
    assert result.source == "model_year"


def test_parse_years_phrase_only():
    result = parse_estimated_age("~3-5 years", now_year=2026)
    assert result is not None
    assert result.years_min == 3
    assert result.years_max == 5
    assert result.source == "years_phrase"


def test_parse_year_range():
    result = parse_estimated_age("Manufactured 2020-2022", now_year=2026)
    assert result is not None
    assert result.years_min == 4
    assert result.years_max == 6


def test_parse_unknown_returns_none():
    assert parse_estimated_age("Unknown") is None


def test_build_asset_age_display_from_model_years():
    llm = LLMAnalysisResult(
        asset_name="Laptop",
        estimated_model_year_min=2020,
        estimated_model_year_max=2021,
    )
    display = build_asset_age_display(llm, now_year=2026)
    assert display.model_years == "2020–2021"
    assert display.age_years == "~5–6 years (as of 2026)"
    assert display.as_of_year == 2026


def test_build_asset_age_display_legacy_string():
    llm = LLMAnalysisResult(
        asset_name="Laptop",
        estimated_age="~3-4 years (approx. 2020-2021)",
    )
    display = build_asset_age_display(llm, now_year=2026)
    assert display.model_years == "2020–2021"
    assert display.age_years == "~5–6 years (as of 2026)"


def test_resolve_asset_age_prefers_structured_model_years():
    llm = LLMAnalysisResult(
        asset_name="Laptop",
        estimated_model_year_min=2021,
        estimated_model_year_max=2021,
        estimated_age="~3-4 years (approx. 2020-2021)",
    )
    parsed = resolve_asset_age(llm, now_year=2026)
    assert parsed is not None
    assert parsed.years_min == 5
    assert parsed.years_max == 5
    assert parsed.source == "model_year"


def test_resolve_asset_age_prefers_model_years_over_valuation_inputs():
    from app.models.responses import LLMValuationInputs

    llm = LLMAnalysisResult(
        asset_name="AC Unit",
        estimated_model_year_min=2022,
        estimated_model_year_max=2022,
        valuation_inputs=LLMValuationInputs(age_years_min=1, age_years_max=2),
    )
    parsed = resolve_asset_age(llm, now_year=2026)
    assert parsed is not None
    assert parsed.source == "model_year"
    assert parsed.years_min == 4
    assert parsed.years_max == 4
