"""Tests for category-aware repair policy."""

from app.models.responses import ConditionReport, DamageItem, LLMAnalysisResult, LLMValuationInputs
from app.services.repair_policy import build_repair_plan


def test_industrial_minor_scratch_acceptable():
    llm = LLMAnalysisResult(
        category="Industrial machine",
        valuation_inputs=LLMValuationInputs(market_segment="industrial"),
    )
    condition = ConditionReport(
        damage_items=[
            DamageItem(type="scratch", severity="minor", location="bed", affects_function=False),
        ],
    )
    plan = build_repair_plan(llm, condition)
    assert plan.items[0].acceptable_wear is True
    assert plan.items[0].repair_needed.value == "none"


def test_laptop_screen_crack_requires_repair():
    llm = LLMAnalysisResult(
        category="Laptop",
        valuation_inputs=LLMValuationInputs(market_segment="it_equipment"),
    )
    condition = ConditionReport(
        damage_items=[
            DamageItem(type="crack", severity="severe", location="screen", affects_function=True),
        ],
    )
    plan = build_repair_plan(llm, condition)
    assert plan.items[0].repair_needed.value == "required"
    assert plan.items[0].repair_urgency.value == "immediate"
