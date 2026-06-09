"""Post-LLM ERP validation for V6 demo — additive fields only, no vision overrides."""

from __future__ import annotations

import re

from app.models.demo_context import DemoContext, infer_location_profile
from app.models.responses import (
    AssetDetails,
    ConditionReport,
    DemoVerification,
    Identifiers,
    LLMAnalysisResult,
    PhotoAngleStatus,
    Valuation,
)
from app.pipeline.tag_crop import crop_hint_from_placement
from app.utils.valuation_bullets import dedupe_bullets

_ANGLE_SPECS: tuple[tuple[str, str, str], ...] = (
    ("front", "Front / primary face", "angle_missing_front"),
    ("tag_closeup", "Tag close-up", "angle_missing_tag_closeup"),
    ("damage_closeup", "Damage close-up", "angle_missing_damage_closeup"),
    ("context_wide", "Context wide shot", "angle_missing_context_wide"),
)

_RUST_KEYWORDS = re.compile(
    r"\b(rust|corrosion|corroded|oxidiz|oxidation)\b",
    re.IGNORECASE,
)
_OUTDOOR_HINTS = re.compile(
    r"\b(outdoor|condenser|underbody|chassis|generator|exterior|roof)\b",
    re.IGNORECASE,
)


def _norm_category(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[^a-z0-9]+", "", value.strip().lower())


def _uncertainty_flags(llm: LLMAnalysisResult) -> set[str]:
    if not llm.reasoning or not llm.reasoning.uncertainty_flags:
        return set()
    return {str(f).strip().lower() for f in llm.reasoning.uncertainty_flags if f}


def _build_photo_angles(flags: set[str]) -> tuple[list[PhotoAngleStatus], int]:
    angles: list[PhotoAngleStatus] = []
    missing = 0
    for angle_id, label, flag in _ANGLE_SPECS:
        satisfied = flag not in flags
        if not satisfied:
            missing += 1
        angles.append(
            PhotoAngleStatus(
                id=angle_id,
                label=label,
                required=True,
                satisfied=satisfied,
            )
        )
    score = max(1, 5 - missing)
    return angles, score


def _damage_mentions_rust(condition: ConditionReport) -> bool:
    for item in condition.damage_items or []:
        blob = " ".join(
            filter(
                None,
                [item.type, item.detail, item.location],
            )
        )
        if _RUST_KEYWORDS.search(blob):
            return True
    if condition.summary and _RUST_KEYWORDS.search(condition.summary):
        return True
    return False


def _functional_appearance(condition: ConditionReport) -> str | None:
    status = (condition.functional_status or "").strip()
    if status:
        return status
    if condition.functional_issues:
        return "Issues noted"
    if condition.usability:
        return condition.usability
    return None


def _nbv_vs_market_points(valuation: Valuation) -> list[str]:
    """Book NBV vs market/as-is only — no climate or LLM prose duplication."""
    parts: list[str] = []
    if valuation.nbv and valuation.nbv.method == "erp_book_nbv":
        parts.append("Book NBV from ERP is the accounting baseline on the books.")
    as_is = valuation.as_is.inr if valuation.as_is else None
    nbv = valuation.nbv.inr if valuation.nbv else None
    if as_is and nbv and as_is.min is not None and nbv.min is not None:
        as_mid = (as_is.min + (as_is.max or as_is.min)) / 2
        nbv_mid = (nbv.min + (nbv.max or nbv.min)) / 2
        if nbv_mid > 0:
            if as_mid < nbv_mid * 0.9:
                parts.append(
                    "Estimated market/as-is value is below book NBV — "
                    "condition or location wear may exceed straight-line depreciation."
                )
            elif as_mid > nbv_mid * 1.1:
                parts.append(
                    "Estimated market/as-is value is above book NBV — "
                    "the asset may be holding resale value better than books suggest."
                )
            else:
                parts.append(
                    "Estimated market/as-is value is broadly in line with book NBV."
                )
    return dedupe_bullets(parts)


def enrich_demo_verification(
    ctx: DemoContext,
    llm: LLMAnalysisResult,
    identifiers: Identifiers,
    condition: ConditionReport,
    asset: AssetDetails,
    valuation: Valuation,
    base: DemoVerification,
) -> DemoVerification:
    """Append server-computed ERP validation fields; never mutate vision outputs."""
    flags = _uncertainty_flags(llm)
    photo_angles, photo_score = _build_photo_angles(flags)
    warnings: list[str] = []

    tag_visible = bool(
        identifiers.barcode.present
        or (identifiers.asset_tag_number_raw or "").strip()
        or (identifiers.asset_tag_number or "").strip()
    )
    tag_readable = identifiers.tag_readable

    erp_cat = (ctx.category or "").strip() or None
    vision_cat = (asset.category or llm.category or "").strip() or None
    cat_match: bool | None = None
    if erp_cat and vision_cat:
        cat_match = _norm_category(erp_cat) == _norm_category(vision_cat)
        if cat_match is False:
            warnings.append("category_mismatch")

    profile = base.location_profile or infer_location_profile(ctx.location)
    rust_noted = _damage_mentions_rust(condition)
    if profile == "coastal_humid" and condition.has_damage and not rust_noted:
        outdoor = any(
            _OUTDOOR_HINTS.search(
                " ".join(filter(None, [d.location, d.type, d.detail]))
            )
            for d in (condition.damage_items or [])
        )
        if outdoor or (ctx.category or "").lower() in ("hvac", "vehicle", "industrial"):
            warnings.append("coastal_rust_not_documented")

    if tag_readable and not identifiers.barcode.present:
        warnings.append("tag_readable_without_barcode")

    if tag_readable and not identifiers.asset_tag_number:
        warnings.append("tag_readable_without_normalized_digits")

    if base.make_match is False and not any(
        k in flags for k in ("generation_ambiguous", "partial_view", "label_unreadable")
    ):
        warnings.append("make_mismatch_unflagged")

    tag_zoom = crop_hint_from_placement(
        identifiers.barcode.placement if identifiers.barcode else None,
        fallback_image_index=llm.barcode_seen_in_image,
    )

    suggests_review = (
        "tag_readable_without_normalized_digits" in warnings
        or "tag_readable_without_barcode" in warnings
    )

    return base.model_copy(
        update={
            "tag_visible": tag_visible,
            "tag_readable": tag_readable,
            "erp_category": erp_cat,
            "vision_category": vision_cat,
            "category_match": cat_match,
            "rust_corrosion_noted": rust_noted if condition.has_damage else None,
            "functional_appearance": _functional_appearance(condition),
            "photo_coverage_score": photo_score,
            "photo_angles": photo_angles,
            "nbv_vs_market_points": _nbv_vs_market_points(valuation),
            "validation_warnings": warnings,
            "tag_zoom_hint": tag_zoom,
            "suggests_review": suggests_review,
        }
    )
