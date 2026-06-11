"""Tests for NBV vs as-is midpoint comparison."""

from app.models.responses import (
    MoneyRange,
    NbvEstimate,
    Valuation,
    ValuationAmount,
    ValuationStatus,
)
from app.services.nbv_engine import apply_nbv_comparison
from tests.market_fixtures import IN_MARKET


def _valuation(
    as_is_min: float,
    as_is_max: float,
    nbv_min: float,
    nbv_max: float,
    *,
    status: ValuationStatus = ValuationStatus.OK,
    fx: float = 83.0,
) -> Valuation:
    return Valuation(
        status=status,
        as_is=ValuationAmount(
            usd=MoneyRange(min=as_is_min, max=as_is_max),
            inr=MoneyRange(min=as_is_min * fx, max=as_is_max * fx),
            display=MoneyRange(min=as_is_min * fx, max=as_is_max * fx),
            display_currency="INR",
        ),
        nbv=NbvEstimate(
            usd=MoneyRange(min=nbv_min, max=nbv_max),
            inr=MoneyRange(min=nbv_min * fx, max=nbv_max * fx),
            display=MoneyRange(min=nbv_min * fx, max=nbv_max * fx),
            display_currency="INR",
        ),
    )


def test_nbv_exceeds_as_is_true():
    val = apply_nbv_comparison(_valuation(200, 220, 400, 440), IN_MARKET)
    assert val.nbv_exceeds_as_is is True
    assert "more than 10%" in (val.nbv_vs_as_is_note or "").lower()


def test_nbv_exceeds_as_is_false():
    val = apply_nbv_comparison(_valuation(500, 550, 300, 330), IN_MARKET)
    assert val.nbv_exceeds_as_is is False


def test_indicative_status_still_compares():
    val = apply_nbv_comparison(
        _valuation(100, 120, 400, 440, status=ValuationStatus.INDICATIVE_ONLY),
        IN_MARKET,
    )
    assert val.nbv_exceeds_as_is is True


def test_within_ten_percent_tolerance_not_flagged():
    """NBV slightly above as-is but within ±10% → No impairment flag."""
    val = apply_nbv_comparison(
        _valuation(24846 / 83, 29168 / 83, 26273 / 83, 29628 / 83, fx=83.0),
        IN_MARKET,
    )
    assert val.nbv_exceeds_as_is is False
    assert "within" in (val.nbv_vs_as_is_note or "").lower()


def test_just_above_ten_percent_tolerance_flagged():
    val = apply_nbv_comparison(_valuation(100, 100, 110.1, 110.1, fx=1.0), IN_MARKET)
    assert val.nbv_exceeds_as_is is True
