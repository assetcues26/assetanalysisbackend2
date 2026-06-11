"""Multi-market valuation and registry tests."""

from app.config import Settings
from app.markets.registry import build_gemini_market_prompt, resolve_market
from app.models.responses import ConditionReport, LLMAnalysisResult, LLMValuationInputs
from app.services.identity_validator import IdentityValidationResult
from app.services.valuation_engine import compute_valuation
from tests.market_fixtures import GB_MARKET, IN_MARKET, US_MARKET


def _identity_ok() -> IdentityValidationResult:
    return IdentityValidationResult(passed=True, identity_confidence=0.9)


def _sample_llm() -> LLMAnalysisResult:
    return LLMAnalysisResult(
        brand="Dell",
        model="Latitude 5420",
        category="Laptop",
        estimated_age="~3 years",
        confidence_asset_condition=0.85,
        valuation_confidence=0.8,
        valuation_inputs=LLMValuationInputs(
            market_segment="it_equipment",
            reference_like_new_usd=1000,
            age_years_min=3,
            age_years_max=3,
        ),
    )


def test_resolve_market_defaults_invalid_to_in():
    market = resolve_market("XX", Settings())
    assert market.region == "IN"
    assert market.currency == "INR"


def test_multi_market_disabled_forces_in():
    settings = Settings(multi_market_enabled=False)
    market = resolve_market("US", settings)
    assert market.region == "IN"


def test_india_valuation_uses_inr_display():
    val = compute_valuation(
        _sample_llm(),
        ConditionReport(overall_score=70),
        _identity_ok(),
        usd_to_display=83.0,
        market=IN_MARKET,
        valuation_confidence_min=0.75,
    )
    assert val.as_is.display_currency == "INR"
    assert val.as_is.inr.min == val.as_is.display.min
    assert "India" in val.currency_note


def test_us_valuation_uses_usd_display():
    val = compute_valuation(
        _sample_llm(),
        ConditionReport(overall_score=70),
        _identity_ok(),
        usd_to_display=1.0,
        market=US_MARKET,
        valuation_confidence_min=0.75,
    )
    assert val.as_is.display_currency == "USD"
    assert val.as_is.display.min == val.as_is.usd.min
    assert val.as_is.inr.min is None
    assert "United States" in val.currency_note


def test_gb_valuation_uses_gbp_display():
    val = compute_valuation(
        _sample_llm(),
        ConditionReport(overall_score=70),
        _identity_ok(),
        usd_to_display=0.79,
        market=GB_MARKET,
        valuation_confidence_min=0.75,
    )
    assert val.as_is.display_currency == "GBP"
    assert val.as_is.display.min is not None
    assert "United Kingdom" in val.currency_note


def test_gemini_prompts_differ_by_region():
    assert "India" in build_gemini_market_prompt(IN_MARKET)
    assert "United States" in build_gemini_market_prompt(US_MARKET)
    assert "United Kingdom" in build_gemini_market_prompt(GB_MARKET)
