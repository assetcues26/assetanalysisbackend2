"""Build client-safe reasoning summary from LLM trace."""

from __future__ import annotations

from app.models.responses import IdentityCandidate, LLMAnalysisResult, ReasoningSummary


def build_reasoning_summary(llm: LLMAnalysisResult) -> ReasoningSummary:
    reasoning = llm.reasoning
    candidates = [
        IdentityCandidate(
            label=c.label or "Unknown",
            visual_cues_for=list(c.visual_cues_for or []),
            visual_cues_against=list(c.visual_cues_against or []),
            confidence=float(c.confidence or 0.0),
        )
        for c in (reasoning.identity_candidates or [])
        if c.label
    ]

    parts: list[str] = []
    if reasoning.selected_identity_rationale:
        parts.append(reasoning.selected_identity_rationale)
    if reasoning.damage_notes:
        parts.append(reasoning.damage_notes)
    if reasoning.repair_judgement_notes:
        parts.append(reasoning.repair_judgement_notes)
    if reasoning.age_estimation_rationale:
        parts.append(reasoning.age_estimation_rationale)
    if reasoning.valuation_deliberation_notes:
        parts.append(reasoning.valuation_deliberation_notes)

    narrative = " ".join(parts).strip() or None

    return ReasoningSummary(
        identity_candidates=candidates,
        selected_identity_rationale=reasoning.selected_identity_rationale,
        uncertainty_flags=list(reasoning.uncertainty_flags or []),
        damage_notes=reasoning.damage_notes,
        repair_judgement_notes=reasoning.repair_judgement_notes,
        narrative=narrative,
    )
