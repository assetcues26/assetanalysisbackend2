"""Age on asset must drive valuation/NBV even when LLM omits structured year fields."""

from app.models.responses import AssetDetails, ConditionReport, LLMAnalysisResult, LLMValuationInputs
from app.services.identity_validator import IdentityValidationResult
from app.services.nbv_engine import apply_nbv_proxy
from app.services.valuation_engine import compute_valuation
from tests.market_fixtures import IN_MARKET


def test_valuation_uses_asset_model_years_when_llm_omits_them():
    llm = LLMAnalysisResult(
        brand="Micromax",
        model="Unidentified",
        category="HVAC",
        asset_type="Split Air Conditioner",
        confidence_asset_name=0.95,
        confidence_asset_condition=0.95,
        valuation_confidence=0.85,
        valuation_inputs=LLMValuationInputs(market_segment="other"),
    )
    asset = AssetDetails(
        name="Micromax Split Air Conditioner",
        estimated_model_years="2022–2023",
        estimated_age_years="~3–4 years (as of 2026)",
        age_as_of_year=2026,
    )
    identity = IdentityValidationResult(
        passed=True,
        identity_confidence=0.95,
        generation_ambiguous=True,
    )
    val = compute_valuation(
        llm,
        ConditionReport(overall_score=95),
        identity,
        usd_to_display=83.0,
        market=IN_MARKET,
        valuation_confidence_min=0.75,
        asset=asset,
    )
    assert val.as_is.usd.min is not None
    val = apply_nbv_proxy(val, llm, usd_to_display=83.0, market=IN_MARKET, asset=asset)
    assert val.nbv is not None
    assert val.nbv.age_years_used is not None
