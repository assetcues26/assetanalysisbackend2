"""Deterministic fair-market valuation from structured analysis inputs."""

from __future__ import annotations

from app.config import Settings, get_settings
from app.models.responses import (
    AssetDetails,
    ConditionReport,
    LLMAnalysisResult,
    MarketSegment,
    MoneyRange,
    Valuation,
    ValuationAmount,
    ValuationStatus,
)
from app.services.age_parser import midpoint_years, resolve_asset_age
from app.services.identity_validator import IdentityValidationResult
from app.services.reference_data import load_reference_data, valuation_rules


def _resolve_segment(llm: LLMAnalysisResult, data: dict) -> str:
    seg = (llm.valuation_inputs.market_segment or "").strip().lower() if llm.valuation_inputs else ""
    if seg in {s.value for s in MarketSegment}:
        return seg

    cat = (llm.category or llm.asset_type or "").lower()
    keywords = data.get("category_segment_keywords") or {}
    for segment, terms in keywords.items():
        if any(term in cat for term in terms):
            return segment
    return MarketSegment.OTHER.value


def _reference_like_new_usd(llm: LLMAnalysisResult, data: dict, segment: str, rules: dict) -> tuple[float, float]:
    hint_band = float(rules["like_new_hint_band_pct"])
    hint = llm.valuation_inputs.reference_like_new_usd if llm.valuation_inputs else None
    if hint and hint > 0:
        return hint * (1 - hint_band), hint * (1 + hint_band)

    brand = (llm.brand or "").strip().lower()
    model = (llm.model or "").strip().lower()
    for key, band in data.get("brand_model_overrides_usd", {}).items():
        b, m = key.split("|", 1)
        if b in brand and m in model:
            return float(band["min"]), float(band["max"])

    baseline = data["category_baselines_usd"].get(segment, data["category_baselines_usd"]["other"])
    return float(baseline["min"]), float(baseline["max"])


def _condition_multiplier(condition: ConditionReport, llm: LLMAnalysisResult, rules: dict) -> float:
    severity_mult = rules["severity_multipliers"]
    mult = 1.0
    for item in condition.damage_items:
        sev = (item.severity or "").strip().lower() or "unknown"
        mult *= float(severity_mult.get(sev, severity_mult.get("unknown", 0.95)))
    if llm.valuation_inputs and llm.valuation_inputs.condition_adjustment_pct is not None:
        adj = llm.valuation_inputs.condition_adjustment_pct
        mult *= max(0.1, 1.0 + (adj / 100.0))
    if condition.functional_issues:
        mult *= float(rules["functional_issues_multiplier"])
    if condition.overall_score is not None:
        mult *= max(
            float(rules["min_condition_score_factor"]),
            condition.overall_score / 100.0,
        )
    return max(
        float(rules["min_condition_multiplier"]),
        min(float(rules["max_condition_multiplier"]), mult),
    )


def _age_multiplier(segment: str, age_years: float | None, data: dict, rules: dict) -> float:
    if age_years is None:
        return float(rules["age_multiplier_when_unknown"])
    rate = float(data["depreciation_annual_rate"].get(segment, 0.14))
    return max(float(rules["min_age_multiplier"]), (1.0 - rate) ** age_years)


def _amount(usd_min: float | None, usd_max: float | None, usd_to_inr: float) -> ValuationAmount:
    return ValuationAmount(
        usd=MoneyRange(min=usd_min, max=usd_max),
        inr=MoneyRange(
            min=round(usd_min * usd_to_inr, 2) if usd_min is not None else None,
            max=round(usd_max * usd_to_inr, 2) if usd_max is not None else None,
        ),
    )


def compute_valuation(
    llm: LLMAnalysisResult,
    condition: ConditionReport,
    identity: IdentityValidationResult,
    *,
    usd_to_inr: float,
    valuation_confidence_min: float,
    asset: AssetDetails | None = None,
    settings: Settings | None = None,
) -> Valuation:
    settings = settings or get_settings()
    identity_weak = identity.withheld_identity or not identity.passed

    data = load_reference_data(settings)
    rules = valuation_rules(data)
    segment = _resolve_segment(llm, data)
    like_min, like_max = _reference_like_new_usd(llm, data, segment, rules)
    like_mid = (like_min + like_max) / 2

    resolved_age = resolve_asset_age(llm, asset=asset)
    age_years = midpoint_years(resolved_age)

    cond_mult = _condition_multiplier(condition, llm, rules)
    age_mult = _age_multiplier(segment, age_years, data, rules)
    as_is_mid = like_mid * cond_mult * age_mult

    band = float(rules["as_is_band_pct"])
    as_is_min = round(as_is_mid * (1 - band), 2)
    as_is_max = round(as_is_mid * (1 + band), 2)
    if as_is_max > like_max:
        as_is_max = like_max
    if as_is_min > as_is_max:
        as_is_min = round(as_is_max * float(rules["as_is_floor_ratio"]), 2)

    confidence = min(
        identity.identity_confidence,
        float(llm.confidence_asset_condition or 0.0),
        float(llm.valuation_confidence or rules["default_valuation_confidence"]),
    )
    if resolved_age is None and age_years is None:
        confidence = min(confidence, float(rules["missing_age_confidence_cap"]))

    status = ValuationStatus.OK
    if confidence < valuation_confidence_min:
        status = ValuationStatus.INDICATIVE_ONLY
    if identity.generation_ambiguous:
        status = ValuationStatus.INDICATIVE_ONLY
        confidence = min(confidence, float(rules["generation_ambiguous_confidence_cap"]))
    if identity_weak:
        status = ValuationStatus.INDICATIVE_ONLY
        confidence = min(confidence, float(rules["weak_identity_confidence_cap"]))

    assumptions = llm.valuation_inputs.valuation_rationale if llm.valuation_inputs else None
    if identity_weak:
        weak_note = (
            "Indicative only — identity or model not verified; verify before client-facing use."
        )
        assumptions = f"{weak_note} {assumptions}".strip() if assumptions else weak_note
    if not assumptions:
        assumptions = llm.valuation_assumptions
    like_mid_inr = round(like_mid * usd_to_inr, 0)
    if not assumptions:
        assumptions = (
            f"Segment={segment}; condition_mult={cond_mult:.2f}; age_mult={age_mult:.2f}; "
            f"like_new_mid≈₹{like_mid_inr:,.0f}; age_years={age_years}; "
            f"India market context; reference={settings.reference_prices_path or 'default'}."
        )

    return Valuation(
        status=status,
        as_is=_amount(as_is_min, as_is_max, usd_to_inr),
        like_new_reference=_amount(like_min, like_max, usd_to_inr),
        confidence=round(confidence, 3),
        assumptions=assumptions,
        currency_note="All amounts in Indian Rupees (₹), estimated for the India market.",
    )
