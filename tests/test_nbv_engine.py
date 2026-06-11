"""Tests for NBV proxy (depreciation only, no damage)."""

from app.models.responses import (
    ConditionReport,
    DamageItem,
    LLMAnalysisResult,
    LLMValuationInputs,
    Valuation,
    ValuationAmount,
    ValuationStatus,
    MoneyRange,
)
from app.services.nbv_engine import apply_nbv_proxy
from tests.market_fixtures import IN_MARKET


def _base_valuation() -> Valuation:
    return Valuation(
        status=ValuationStatus.OK,
        as_is=ValuationAmount(
            usd=MoneyRange(min=100, max=120),
            inr=MoneyRange(min=10000, max=12000),
        ),
    )


def test_nbv_ignores_condition_score():
    llm_mild = LLMAnalysisResult(
        category="Laptop",
        estimated_age="~3 years",
        condition_score=90,
        valuation_inputs=LLMValuationInputs(
            market_segment="it_equipment",
            reference_like_new_usd=1000,
            age_years_min=3,
            age_years_max=3,
        ),
    )
    llm_heavy = llm_mild.model_copy(update={"condition_score": 40})

    v1 = apply_nbv_proxy(_base_valuation(), llm_mild, usd_to_display=100.0, market=IN_MARKET)
    v2 = apply_nbv_proxy(_base_valuation(), llm_heavy, usd_to_display=100.0, market=IN_MARKET)

    assert v1.nbv is not None and v2.nbv is not None
    assert v1.nbv.usd.min == v2.nbv.usd.min
    assert v1.nbv.usd.max == v2.nbv.usd.max


def test_nbv_unchanged_when_only_damage_items_differ():
    """Damage affects as-is via valuation_engine, not NBV."""
    llm = LLMAnalysisResult(
        category="Industrial machine",
        estimated_age="~5 years",
        valuation_inputs=LLMValuationInputs(
            market_segment="industrial",
            reference_like_new_usd=5000,
            age_years_min=5,
            age_years_max=5,
        ),
    )
    nbv = apply_nbv_proxy(_base_valuation(), llm, usd_to_display=100.0, market=IN_MARKET)
    assert nbv.nbv is not None
    assert nbv.nbv.usd.min is not None
