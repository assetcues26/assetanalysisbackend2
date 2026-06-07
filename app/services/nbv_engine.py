"""Age-derived NBV proxy until ERP book data is available."""

from __future__ import annotations

from app.config import Settings, get_settings
from app.models.responses import AssetDetails, LLMAnalysisResult, MoneyRange, NbvEstimate, Valuation
from app.services.age_parser import midpoint_years, resolve_asset_age
from app.services.reference_data import load_reference_data, valuation_rules
from app.services.valuation_engine import _reference_like_new_usd, _resolve_segment

# NBV vs as-is midpoint compare: ignore differences within this band (estimates are approximate).
NBV_AS_IS_TOLERANCE_PCT = 0.10


def _midpoint(min_val: float | None, max_val: float | None) -> float | None:
    if min_val is None or max_val is None:
        return None
    return (min_val + max_val) / 2


def apply_nbv_proxy(
    valuation: Valuation,
    llm: LLMAnalysisResult,
    *,
    usd_to_inr: float,
    asset: AssetDetails | None = None,
    settings: Settings | None = None,
) -> Valuation:
    settings = settings or get_settings()
    data = load_reference_data(settings)
    rules = valuation_rules(data)
    segment = _resolve_segment(llm, data)
    like_min, like_max = _reference_like_new_usd(llm, data, segment, rules)
    like_mid = (like_min + like_max) / 2

    age_years = midpoint_years(resolve_asset_age(llm, asset=asset))

    if age_years is None:
        valuation.nbv = None
        return valuation

    dep_rate = float(data["depreciation_annual_rate"].get(segment, 0.14))
    nbv_mid = like_mid * ((1.0 - dep_rate) ** age_years)
    band = float(rules["nbv_band_pct"])
    nbv_min = round(nbv_mid * (1 - band), 2)
    nbv_max = round(nbv_mid * (1 + band), 2)

    valuation.nbv = NbvEstimate(
        usd=MoneyRange(min=nbv_min, max=nbv_max),
        inr=MoneyRange(
            min=round(nbv_min * usd_to_inr, 2),
            max=round(nbv_max * usd_to_inr, 2),
        ),
        method="age_derived_proxy",
        age_years_used=age_years,
        depreciation_rate_used=dep_rate,
    )
    return valuation


def apply_nbv_comparison(valuation: Valuation) -> Valuation:
    """Compare NBV midpoint vs as-is midpoint; set nbv_exceeds_as_is yes/no."""
    if valuation.nbv is None:
        valuation.nbv_exceeds_as_is = None
        valuation.nbv_vs_as_is_note = None
        return valuation

    nbv_mid = _midpoint(valuation.nbv.inr.min, valuation.nbv.inr.max)
    current_mid = _midpoint(valuation.as_is.inr.min, valuation.as_is.inr.max)

    if nbv_mid is None or current_mid is None:
        valuation.nbv_exceeds_as_is = None
        valuation.nbv_vs_as_is_note = None
        return valuation

    tolerance = NBV_AS_IS_TOLERANCE_PCT
    upper_bound = current_mid * (1.0 + tolerance)
    exceeds = nbv_mid > upper_bound
    valuation.nbv_exceeds_as_is = exceeds

    pct_label = f"{tolerance * 100:.0f}%"
    if exceeds:
        valuation.nbv_vs_as_is_note = (
            f"NBV midpoint (₹{nbv_mid:,.0f}) is more than {pct_label} above the current estimate "
            f"midpoint (₹{current_mid:,.0f}) — book value may be overstated relative to India market "
            "value (possible impairment)."
        )
    elif nbv_mid > current_mid:
        valuation.nbv_vs_as_is_note = (
            f"NBV midpoint (₹{nbv_mid:,.0f}) is slightly above the current estimate midpoint "
            f"(₹{current_mid:,.0f}) but within the ±{pct_label} tolerance — estimates are approximate; "
            "no clear impairment signal."
        )
    else:
        valuation.nbv_vs_as_is_note = (
            f"Current estimate midpoint (₹{current_mid:,.0f}) is at or above NBV midpoint "
            f"(₹{nbv_mid:,.0f}) (±{pct_label} tolerance applied)."
        )

    return valuation
