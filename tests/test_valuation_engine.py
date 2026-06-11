"""Tests for deterministic valuation engine."""

from app.models.responses import ConditionReport, DamageItem, LLMAnalysisResult, LLMValuationInputs, ValuationStatus
from app.services.identity_validator import IdentityValidationResult
from app.services.valuation_engine import compute_valuation
from tests.market_fixtures import IN_MARKET


def _identity_ok() -> IdentityValidationResult:
    return IdentityValidationResult(passed=True, identity_confidence=0.9)


def test_as_is_not_above_like_new():
    llm = LLMAnalysisResult(
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
    condition = ConditionReport(
        overall_score=70,
        damage_items=[DamageItem(type="scratch", severity="minor")],
    )
    val = compute_valuation(
        llm, condition, _identity_ok(), usd_to_display=100.0, market=IN_MARKET, valuation_confidence_min=0.75
    )
    assert val.status in (ValuationStatus.OK, ValuationStatus.INDICATIVE_ONLY)
    assert val.as_is.usd.max is not None
    assert val.like_new_reference.usd.max is not None
    assert val.as_is.usd.max <= val.like_new_reference.usd.max


def test_as_is_decreases_with_severe_damage():
    llm = LLMAnalysisResult(
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
    mild = ConditionReport(
        overall_score=85,
        damage_items=[DamageItem(type="scratch", severity="minor")],
    )
    heavy = ConditionReport(
        overall_score=40,
        damage_items=[
            DamageItem(type="crack", severity="severe"),
            DamageItem(type="dent", severity="severe"),
        ],
    )
    mild_val = compute_valuation(llm, mild, _identity_ok(), usd_to_display=100.0, market=IN_MARKET, valuation_confidence_min=0.75)
    heavy_val = compute_valuation(llm, heavy, _identity_ok(), usd_to_display=100.0, market=IN_MARKET, valuation_confidence_min=0.75)
    assert mild_val.as_is.usd.max is not None and heavy_val.as_is.usd.max is not None
    assert heavy_val.as_is.usd.max < mild_val.as_is.usd.max


def test_weak_identity_still_returns_ok_status_and_amounts():
    llm = LLMAnalysisResult(
        brand="Apple",
        model="Unidentified",
        category="Phone",
        estimated_model_year_min=2021,
        estimated_model_year_max=2021,
        valuation_inputs=LLMValuationInputs(market_segment="consumer_electronics"),
    )
    condition = ConditionReport()
    identity = IdentityValidationResult(passed=False, identity_confidence=0.4, withheld_identity=True)
    val = compute_valuation(llm, condition, identity, usd_to_display=100.0, market=IN_MARKET, valuation_confidence_min=0.75)
    assert val.status == ValuationStatus.OK
    assert val.as_is.usd.min is not None
    assert val.as_is.usd.max is not None
    assert val.assumptions
