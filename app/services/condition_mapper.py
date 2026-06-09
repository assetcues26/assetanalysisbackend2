"""Map LLM condition/damage fields into API condition report (single Gemini call)."""

import re

from app.models.responses import DamageItem, LLMAnalysisResult, LLMDamageItem, RepairNeeded, RepairUrgency
from app.services.field_merger import _clean_list
from app.services.placement_mapper import placement_from_parts

_DAMAGE_KEYWORDS = re.compile(
    r"\b(dent|scratch|crack|chip|stain|rust|corrosion|damage|broken|missing|"
    r"deform|bent|tear|hole|scuff)\b",
    re.IGNORECASE,
)
_LABEL_HINTS = re.compile(
    r"\b(label|sticker|rating|branding|nameplate|warning|refrigerant|logo)\b",
    re.IGNORECASE,
)


def _clamp_seen_in_image(value: int | None, max_images: int) -> int | None:
    if not isinstance(value, int) or max_images < 1:
        return None
    if 1 <= value <= max_images:
        return value
    return None


def _infer_damage_image_index(
    raw: LLMDamageItem,
    max_images: int,
    barcode_seen_in_image: int | None = None,
) -> int | None:
    """Infer seen_in_image from location/detail text when LLM omits it."""
    if max_images == 1:
        return 1
    # Try to extract "Image N" from detail text
    if raw.detail:
        match = re.search(r'\bimage\s*(\d+)\b', raw.detail, re.IGNORECASE)
        if match:
            idx = int(match.group(1))
            if 1 <= idx <= max_images:
                return idx
    # Try to infer from location field
    location = (raw.location or "").lower()
    if ("side" in location) and barcode_seen_in_image is not None:
        return barcode_seen_in_image
    return None


def _to_damage_item(
    raw: LLMDamageItem,
    max_images: int,
    barcode_seen_in_image: int | None = None,
) -> DamageItem | None:
    location = (raw.location or "").strip() or None
    dtype = (raw.type or "").strip() or None
    if not location and not dtype and not raw.detail:
        return None

    placement = placement_from_parts(
        asset_location=location,
        horizontal=raw.horizontal,
        vertical=raw.vertical,
        seen_in_image=raw.seen_in_image,
        in_frame_position=raw.in_frame_position,
        max_images=max_images,
    )
    seen = _clamp_seen_in_image(raw.seen_in_image, max_images)
    if seen is None:
        seen = _infer_damage_image_index(raw, max_images, barcode_seen_in_image)
    if placement and seen is not None:
        placement = placement.model_copy(update={"seen_in_image": seen})

    repair_needed = None
    repair_urgency = None
    if raw.repair_needed:
        try:
            repair_needed = RepairNeeded(raw.repair_needed.strip().lower())
        except ValueError:
            repair_needed = None
    if raw.repair_urgency:
        try:
            repair_urgency = RepairUrgency(raw.repair_urgency.strip().lower())
        except ValueError:
            repair_urgency = None

    return DamageItem(
        location=location,
        type=dtype,
        severity=(raw.severity or "").strip() or None,
        seen_in_image=seen,
        detail=(raw.detail or "").strip() or None,
        affects_function=raw.affects_function,
        repair_action=(raw.repair_action or "").strip() or None,
        repair_needed=repair_needed,
        repair_urgency=repair_urgency,
        acceptable_wear=raw.acceptable_wear,
        placement=placement,
    )


def _synthetic_from_issues(
    issues: list[str],
    issue_type: str,
    max_images: int,
) -> list[DamageItem]:
    items: list[DamageItem] = []
    for text in _clean_list(issues, limit=10):
        items.append(
            DamageItem(
                location=None,
                type=issue_type,
                severity="moderate",
                seen_in_image=None,
                detail=text,
                affects_function=issue_type == "functional",
                repair_action=None,
                placement=None,
            )
        )
    return items


def merge_damage_sources(llm: LLMAnalysisResult, max_images: int) -> list[DamageItem]:
    barcode_seen: int | None = None
    if isinstance(llm.barcode_seen_in_image, int) and 1 <= llm.barcode_seen_in_image <= max_images:
        barcode_seen = llm.barcode_seen_in_image

    items: list[DamageItem] = []
    seen: set[tuple[str | None, str | None]] = set()

    for raw in llm.damage_items or []:
        item = _to_damage_item(raw, max_images, barcode_seen)
        if item is None:
            continue
        key = (item.location, item.type)
        if key in seen:
            continue
        seen.add(key)
        items.append(item)

    if not items:
        items.extend(_synthetic_from_issues(llm.functional_issues, "functional", max_images))
        items.extend(_synthetic_from_issues(llm.missing_parts, "missing part", max_images))

    return items[:50]


def damage_needs_review(llm: LLMAnalysisResult) -> bool:
    if llm.damage_items:
        return False
    summary = llm.condition_summary or ""
    cosmetic = llm.cosmetic_condition or ""
    combined = f"{summary} {cosmetic}"
    if not _DAMAGE_KEYWORDS.search(combined):
        return False
    return True


def stickers_need_review(llm: LLMAnalysisResult) -> bool:
    if llm.stickers:
        return False
    if _clean_list(llm.visible_labels):
        return False
    if _clean_list(llm.specifications) or _clean_list(llm.distinguishing_features):
        return False
    desc = llm.description or ""
    return bool(_LABEL_HINTS.search(desc))


def build_damage_items(llm: LLMAnalysisResult, images_analyzed: int) -> list[DamageItem]:
    return merge_damage_sources(llm, images_analyzed)


_GRADE_ALIASES = {
    "excellent": "Excellent",
    "good": "Good",
    "fair": "Fair",
    "average": "Fair",
    "moderate": "Fair",
    "poor": "Poor",
    "bad": "Poor",
    "damaged": "Poor",
    "critical": "Poor",
}


def _score_to_hundred(score: int | float | None) -> int | None:
    if score is None:
        return None
    try:
        s = int(round(float(score)))
    except (TypeError, ValueError):
        return None
    if 1 <= s <= 10:
        s *= 10
    return max(0, min(100, s))


def resolve_condition_grade(grade: str | None, score: int | float | None = None) -> str | None:
    """Normalize LLM grade; derive from condition_score when grade is missing."""
    if grade:
        key = str(grade).strip().lower()
        if key in _GRADE_ALIASES:
            return _GRADE_ALIASES[key]
        if key not in ("unknown", "n/a", "na", ""):
            return str(grade).strip().title()

    normalized = _score_to_hundred(score)
    if normalized is None:
        return None
    if normalized >= 85:
        return "Excellent"
    if normalized >= 70:
        return "Good"
    if normalized >= 50:
        return "Fair"
    return "Poor"
