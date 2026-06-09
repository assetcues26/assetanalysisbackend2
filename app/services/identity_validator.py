"""Validate and gate asset identity from LLM reasoning output."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.responses import LLMAnalysisResult, MarketSegment

_ELECTRONICS_CATEGORIES = {
    "phone",
    "smartphone",
    "mobile",
    "laptop",
    "notebook",
    "tablet",
    "computer",
    "monitor",
    "electronics",
    "consumer electronics",
    "it equipment",
}


@dataclass
class IdentityValidationResult:
    passed: bool
    identity_confidence: float
    uncertainty_flags: list[str] = field(default_factory=list)
    generation_ambiguous: bool = False
    withheld_identity: bool = False


def _is_electronics(llm: LLMAnalysisResult) -> bool:
    blob = " ".join(
        filter(
            None,
            [
                llm.category,
                llm.asset_type,
                llm.asset_name,
                llm.valuation_inputs.market_segment if llm.valuation_inputs else None,
            ],
        )
    ).lower()
    if llm.valuation_inputs and llm.valuation_inputs.market_segment in (
        MarketSegment.CONSUMER_ELECTRONICS.value,
        MarketSegment.IT_EQUIPMENT.value,
    ):
        return True
    return any(term in blob for term in _ELECTRONICS_CATEGORIES)


def validate_identity(llm: LLMAnalysisResult, *, min_confidence: float = 0.75) -> IdentityValidationResult:
    flags = list(llm.reasoning.uncertainty_flags or [])
    confidence = float(llm.confidence_asset_name or 0.0)
    candidates = llm.reasoning.identity_candidates or []

    if confidence < min_confidence:
        flags.append("low_identity_confidence")

    if _is_electronics(llm):
        if len(candidates) < 2:
            flags.append("insufficient_identity_candidates")
        top_two = sorted(candidates, key=lambda c: c.confidence or 0.0, reverse=True)[:2]
        if len(top_two) >= 2 and abs((top_two[0].confidence or 0) - (top_two[1].confidence or 0)) < 0.15:
            flags.append("generation_ambiguous")

    generation_ambiguous = "generation_ambiguous" in flags
    # Production demo: flag quality issues but do not block output or rewrite identity.
    withheld = confidence < min_confidence
    passed = not withheld

    return IdentityValidationResult(
        passed=passed,
        identity_confidence=confidence,
        uncertainty_flags=sorted(set(flags)),
        generation_ambiguous=generation_ambiguous,
        withheld_identity=withheld,
    )
