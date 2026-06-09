"""Tests for identity validation."""

from app.models.responses import LLMIdentityCandidate, LLMReasoningTrace, LLMAnalysisResult
from app.services.identity_validator import validate_identity


def test_electronics_single_candidate_flags_but_passes():
    llm = LLMAnalysisResult(
        asset_name="Apple iPhone",
        category="Smartphone",
        brand="Apple",
        model="iPhone 15",
        confidence_asset_name=0.9,
        reasoning=LLMReasoningTrace(
            identity_candidates=[
                LLMIdentityCandidate(label="iPhone 15", confidence=0.9, visual_cues_for=["a"]),
            ],
            uncertainty_flags=[],
        ),
    )
    result = validate_identity(llm)
    assert result.passed
    assert "insufficient_identity_candidates" in result.uncertainty_flags
    assert not result.withheld_identity


def test_high_confidence_with_candidates_passes():
    llm = LLMAnalysisResult(
        asset_name="Dell Latitude 5420",
        category="Laptop",
        brand="Dell",
        model="Latitude 5420",
        confidence_asset_name=0.9,
        reasoning=LLMReasoningTrace(
            identity_candidates=[
                LLMIdentityCandidate(label="Latitude 5420", confidence=0.9, visual_cues_for=["nameplate"]),
                LLMIdentityCandidate(label="Latitude 5410", confidence=0.3, visual_cues_against=["wrong model text"]),
            ],
        ),
    )
    result = validate_identity(llm)
    assert result.passed
