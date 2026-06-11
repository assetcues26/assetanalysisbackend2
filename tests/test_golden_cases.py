"""Golden-case regression tests (synthetic, no live Gemini)."""

import json
from pathlib import Path

import pytest

from app.models.responses import (
    ConditionReport,
    DamageItem,
    LLMAnalysisResult,
    LLMIdentityCandidate,
    LLMReasoningTrace,
    LLMValuationInputs,
    ValuationStatus,
)
from app.services.identity_validator import validate_identity
from app.services.repair_policy import build_repair_plan
from app.services.nbv_engine import apply_nbv_comparison, apply_nbv_proxy
from app.services.valuation_engine import compute_valuation
from tests.market_fixtures import IN_MARKET

_FIXTURES = Path(__file__).parent / "fixtures" / "golden" / "cases.json"


@pytest.fixture
def golden_cases():
    with _FIXTURES.open(encoding="utf-8") as fh:
        return json.load(fh)


def test_golden_valuation_bounds(golden_cases):
    for case in golden_cases:
        if "expect_as_is_lte_like_new" not in case:
            continue
        llm = LLMAnalysisResult(
            brand=case.get("brand"),
            model=case.get("model"),
            category=case.get("category"),
            estimated_age=f"~{case.get('age_years', 3)} years",
            confidence_asset_name=0.9,
            confidence_asset_condition=0.85,
            valuation_confidence=0.8,
            valuation_inputs=LLMValuationInputs(
                market_segment=case["market_segment"],
                reference_like_new_usd=case["reference_like_new_usd"],
                age_years_min=case.get("age_years"),
                age_years_max=case.get("age_years"),
            ),
            reasoning=LLMReasoningTrace(
                identity_candidates=[
                    LLMIdentityCandidate(label=case.get("model", "A"), confidence=0.9),
                    LLMIdentityCandidate(label="Alt", confidence=0.2),
                ],
            ),
        )
        damages = [
            DamageItem(type="dent", severity=sev) for sev in case.get("damage_severity", [])
        ]
        condition = ConditionReport(overall_score=case.get("condition_score"), damage_items=damages)
        identity = validate_identity(llm)
        val = compute_valuation(llm, condition, identity, usd_to_display=100.0, market=IN_MARKET, valuation_confidence_min=0.75)
        if val.as_is.usd.max is not None and val.like_new_reference.usd.max is not None:
            assert val.as_is.usd.max <= val.like_new_reference.usd.max, case["id"]


def test_golden_repair_policy(golden_cases):
    for case in golden_cases:
        if "expect_repair_needed" not in case:
            continue
        llm = LLMAnalysisResult(
            category=case["category"],
            valuation_inputs=LLMValuationInputs(market_segment=case["market_segment"]),
        )
        condition = ConditionReport(
            damage_items=[
                DamageItem(
                    type=case.get("damage_type", "scratch"),
                    severity=case.get("damage_severity", "minor"),
                ),
            ],
        )
        plan = build_repair_plan(llm, condition)
        assert plan.items[0].repair_needed.value == case["expect_repair_needed"], case["id"]
        if case.get("expect_acceptable_wear") is not None:
            assert plan.items[0].acceptable_wear == case["expect_acceptable_wear"], case["id"]


def test_golden_identity(golden_cases):
    for case in golden_cases:
        if "expect_identity_pass" not in case:
            continue
        candidates = [
            LLMIdentityCandidate(label="Primary", confidence=0.9),
        ]
        if case.get("candidate_count", 2) >= 2:
            candidates.append(LLMIdentityCandidate(label="Alt", confidence=0.2))
        llm = LLMAnalysisResult(
            category=case["category"],
            brand=case.get("brand"),
            model=case.get("model"),
            confidence_asset_name=case.get("confidence_asset_name", 0.9),
            reasoning=LLMReasoningTrace(identity_candidates=candidates),
        )
        result = validate_identity(llm)
        assert result.passed == case["expect_identity_pass"], case["id"]
        if not case["expect_identity_pass"]:
            val = compute_valuation(
                llm,
                ConditionReport(),
                result,
                usd_to_display=100.0, market=IN_MARKET,
                valuation_confidence_min=0.75,
            )
            assert val.status == ValuationStatus.OK, case["id"]
            assert val.as_is.usd.min is not None, case["id"]


def test_golden_nbv_exceeds_as_is(golden_cases):
    for case in golden_cases:
        if "expect_nbv_exceeds_as_is" not in case:
            continue
        llm = LLMAnalysisResult(
            brand=case.get("brand"),
            model=case.get("model"),
            category=case.get("category"),
            estimated_age=f"~{case.get('age_years', 3)} years",
            confidence_asset_name=0.9,
            confidence_asset_condition=0.85,
            valuation_confidence=0.8,
            valuation_inputs=LLMValuationInputs(
                market_segment=case["market_segment"],
                reference_like_new_usd=case["reference_like_new_usd"],
                age_years_min=case.get("age_years"),
                age_years_max=case.get("age_years"),
            ),
            reasoning=LLMReasoningTrace(
                identity_candidates=[
                    LLMIdentityCandidate(label=case.get("model", "A"), confidence=0.9),
                    LLMIdentityCandidate(label="Alt", confidence=0.2),
                ],
            ),
        )
        damages = [
            DamageItem(type="dent", severity=sev) for sev in case.get("damage_severity", [])
        ]
        condition = ConditionReport(overall_score=case.get("condition_score"), damage_items=damages)
        identity = validate_identity(llm)
        val = compute_valuation(llm, condition, identity, usd_to_display=100.0, market=IN_MARKET, valuation_confidence_min=0.75)
        val = apply_nbv_proxy(val, llm, usd_to_display=100.0, market=IN_MARKET)
        val = apply_nbv_comparison(val, IN_MARKET)
        assert val.nbv_exceeds_as_is == case["expect_nbv_exceeds_as_is"], case["id"]
