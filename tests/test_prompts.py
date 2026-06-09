"""Tests for Gemini prompt loading."""

from app.prompts.loader import get_analysis_prompt


def test_analysis_prompt_core_fields():
    prompt = get_analysis_prompt()
    assert "ONE OR MORE photographs" in prompt
    assert "reasoning" in prompt
    assert "identity_candidates" in prompt
    assert "asset_name" in prompt
    assert "damage_items" in prompt
    assert "condition_grade" in prompt
    assert "valuation_inputs" in prompt
    assert "market_segment" in prompt
    assert "repair_needed" in prompt
    assert "acceptable_wear" in prompt


def test_analysis_prompt_v2_framing():
    prompt = get_analysis_prompt()
    assert "engineer" in prompt.lower()
    assert "STEP 1" in prompt
    assert "VALUATION INPUTS ONLY" in prompt
    assert "phone/laptop" in prompt.lower() or "phone/laptop/tablet" in prompt.lower()
    assert "ASSET-CLASS PLAYBOOKS" in prompt
    assert "Excellent|Good|Fair|Poor|Bad" in prompt
    assert "age_estimation_rationale" in prompt
    assert "valuation_deliberation_notes" in prompt
    assert "description: REQUIRED" in prompt
