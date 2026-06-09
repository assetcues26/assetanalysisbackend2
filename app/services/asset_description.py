"""Resolve client-facing asset description when the model omits the dedicated field."""

from __future__ import annotations

from app.models.responses import LLMAnalysisResult

_EMPTY_MARKERS = frozenset({"unknown", "n/a", "na", "null", "—", "-", "none", "not available"})


def _clean_list(items: list[str] | None, limit: int = 25) -> list[str]:
    seen: list[str] = []
    for item in items or []:
        text = str(item).strip()
        if text and text not in seen:
            seen.append(text)
        if len(seen) >= limit:
            break
    return seen


def _is_meaningful(text: str | None) -> bool:
    if not text:
        return False
    cleaned = str(text).strip()
    return bool(cleaned) and cleaned.lower() not in _EMPTY_MARKERS


def resolve_asset_description(llm: LLMAnalysisResult) -> str | None:
    """
    Prefer LLM `description`; otherwise synthesize from identity, condition, and reasoning.
    The model often leaves `description` empty while filling condition_summary instead.
    """
    if _is_meaningful(llm.description):
        return str(llm.description).strip()

    sentences: list[str] = []

    brand_model = " ".join(p for p in [llm.brand, llm.model] if _is_meaningful(p))
    kind = next(
        (p for p in [llm.category, llm.asset_type, llm.asset_name] if _is_meaningful(p)),
        None,
    )
    visual = [p for p in [llm.color, llm.material] if _is_meaningful(p)]
    dims = llm.estimated_dimensions.strip() if _is_meaningful(llm.estimated_dimensions) else None

    if brand_model or kind:
        subject = brand_model or kind or "Asset"
        detail_parts = [*visual]
        if dims:
            detail_parts.append(dims)
        if detail_parts:
            sentences.append(f"{subject}: {', '.join(detail_parts)}.")
        else:
            sentences.append(f"{subject} identified from submitted photographs.")

    for feat in _clean_list(llm.distinguishing_features, limit=3):
        sentences.append(feat if feat.endswith(".") else f"{feat}.")

    specs = _clean_list(llm.specifications, limit=4)
    if specs:
        sentences.append(f"Visible specifications include {', '.join(specs)}.")

    if _is_meaningful(llm.condition_summary):
        sentences.append(str(llm.condition_summary).strip())

    reasoning = llm.reasoning
    if not sentences and _is_meaningful(reasoning.selected_identity_rationale):
        sentences.append(str(reasoning.selected_identity_rationale).strip())

    if not sentences and _is_meaningful(reasoning.damage_notes):
        sentences.append(str(reasoning.damage_notes).strip())

    if not sentences and _is_meaningful(llm.cosmetic_condition):
        sentences.append(str(llm.cosmetic_condition).strip())

    text = " ".join(sentences).strip()
    return text or None
