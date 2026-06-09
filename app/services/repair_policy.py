"""Category-aware repair decisions (engineer-style overrides)."""

from __future__ import annotations

from app.models.responses import (
    ConditionReport,
    DamageItem,
    LLMAnalysisResult,
    RepairNeeded,
    RepairPlan,
    RepairPlanItem,
    RepairUrgency,
)

_SCREEN_TERMS = ("screen", "display", "lcd", "glass", "monitor panel")
_PHONE_LAPTOP_TERMS = ("phone", "smartphone", "laptop", "notebook", "tablet", "macbook", "iphone")
_INDUSTRIAL_TERMS = ("machine", "industrial", "equipment", "lathe", "compressor", "generator", "tool")
_FURNITURE_TERMS = ("furniture", "chair", "desk", "cabinet", "table")
_VEHICLE_TERMS = ("vehicle", "car", "truck", "van", "suv", "nexon", "fleet", "sedan", "hatchback", "jeep")
_VEHICLE_LOCATIONS = ("bumper", "fender", "panel", "door", "hood", "roof", "quarter", "grille", "underbody", "wheel", "tyre", "tire")


def _asset_class(llm: LLMAnalysisResult) -> str:
    blob = " ".join(filter(None, [llm.category, llm.asset_type, llm.asset_name])).lower()
    seg = (llm.valuation_inputs.market_segment or "").lower() if llm.valuation_inputs else ""
    if seg == "vehicle" or any(t in blob for t in _VEHICLE_TERMS):
        return "vehicle"
    if seg in ("consumer_electronics",) or any(t in blob for t in _PHONE_LAPTOP_TERMS):
        return "phone_laptop"
    if seg == "industrial" or any(t in blob for t in _INDUSTRIAL_TERMS):
        return "industrial"
    if seg == "furniture" or any(t in blob for t in _FURNITURE_TERMS):
        return "furniture"
    if seg == "it_equipment":
        return "phone_laptop"
    return "other"


def _parse_repair_needed(raw: str | None) -> RepairNeeded | None:
    if not raw:
        return None
    try:
        return RepairNeeded(raw.strip().lower())
    except ValueError:
        return None


def _parse_urgency(raw: str | None) -> RepairUrgency | None:
    if not raw:
        return None
    try:
        return RepairUrgency(raw.strip().lower())
    except ValueError:
        return None


def _classify_damage(
    item: DamageItem,
    asset_class: str,
    llm_item_repair_needed: str | None = None,
    llm_item_urgency: str | None = None,
    llm_acceptable: bool | None = None,
) -> tuple[RepairNeeded, RepairUrgency, bool, str]:
    dtype = (item.type or "").lower()
    location = (item.location or "").lower()
    severity = (item.severity or "").lower()
    is_screen = any(t in dtype or t in location for t in _SCREEN_TERMS)

    parsed_needed = _parse_repair_needed(llm_item_repair_needed)
    parsed_urgency = _parse_urgency(llm_item_urgency)

    if asset_class == "vehicle":
        is_structural = any(
            t in dtype or t in location
            for t in ("frame", "chassis", "engine", "transmission", "axle", "airbag", "suspension")
        )
        is_bumper_panel = any(
            t in dtype or t in location
            for t in _VEHICLE_LOCATIONS
        ) or dtype in ("dent", "crack", "scratch", "scuff", "paint", "chip", "rust")
        if is_structural or (severity == "severe" and item.affects_function):
            return (
                RepairNeeded.REQUIRED,
                RepairUrgency.IMMEDIATE,
                False,
                "Structural or mechanical vehicle damage requires immediate repair — affects roadworthiness.",
            )
        if is_bumper_panel and severity in ("minor", "moderate"):
            return (
                RepairNeeded.COSMETIC_ONLY,
                RepairUrgency.SCHEDULED,
                severity == "minor",
                "Vehicle body/bumper cosmetic damage. In India, a bumper repair costs ₹5,000–15,000 "
                "and reduces resale by only 3–8%. Does not affect roadworthiness or function.",
            )
        if severity == "minor":
            return (
                RepairNeeded.COSMETIC_ONLY,
                RepairUrgency.NONE,
                True,
                "Minor vehicle surface wear — acceptable for fleet use.",
            )
        return (
            parsed_needed or RepairNeeded.COSMETIC_ONLY,
            parsed_urgency or RepairUrgency.MONITOR,
            llm_acceptable if llm_acceptable is not None else False,
            "Vehicle damage — assess repair before next inspection.",
        )

    if asset_class == "industrial":
        if severity == "severe" or item.affects_function:
            return (
                RepairNeeded.REQUIRED,
                RepairUrgency.SCHEDULED,
                False,
                "Functional or severe damage on industrial equipment requires scheduled maintenance.",
            )
        if severity == "minor" and dtype in ("scratch", "scuff", "fade", "discoloration"):
            return (
                RepairNeeded.NONE,
                RepairUrgency.NONE,
                True,
                "Minor cosmetic wear is acceptable on industrial equipment with no function impact.",
            )
        return (
            parsed_needed or RepairNeeded.COSMETIC_ONLY,
            parsed_urgency or RepairUrgency.MONITOR,
            llm_acceptable if llm_acceptable is not None else False,
            "Monitor wear; repair only if function or safety is affected.",
        )

    if asset_class == "phone_laptop":
        if is_screen or dtype in ("crack", "shatter"):
            return (
                RepairNeeded.REQUIRED,
                RepairUrgency.IMMEDIATE,
                False,
                "Screen or structural damage on consumer electronics affects usability and resale.",
            )
        if severity == "minor" and dtype in ("scratch", "scuff"):
            return (
                RepairNeeded.COSMETIC_ONLY,
                RepairUrgency.NONE,
                False,
                "Minor body scratch — cosmetic only; note for resale grading.",
            )
        if severity == "moderate":
            return (
                RepairNeeded.RECOMMENDED,
                RepairUrgency.SCHEDULED,
                False,
                "Moderate damage on portable electronics — recommend repair before redeployment.",
            )
        return (
            parsed_needed or RepairNeeded.RECOMMENDED,
            parsed_urgency or RepairUrgency.MONITOR,
            False,
            "Assess impact on function and water/dust integrity.",
        )

    if asset_class == "furniture":
        if severity == "severe" or item.affects_function:
            return RepairNeeded.RECOMMENDED, RepairUrgency.SCHEDULED, False, "Structural furniture damage should be repaired."
        return RepairNeeded.COSMETIC_ONLY, RepairUrgency.NONE, True, "Cosmetic furniture wear is generally acceptable."

    return (
        parsed_needed or RepairNeeded.COSMETIC_ONLY,
        parsed_urgency or RepairUrgency.MONITOR,
        llm_acceptable or False,
        "Standard wear assessment — repair if function affected.",
    )


def build_repair_plan(
    llm: LLMAnalysisResult,
    condition: ConditionReport,
) -> RepairPlan:
    asset_class = _asset_class(llm)
    llm_damage_by_key = {
        ((d.location or "").strip().lower(), (d.type or "").strip().lower()): d
        for d in (llm.damage_items or [])
    }

    plan_items: list[RepairPlanItem] = []
    updated_damage: list[DamageItem] = []

    for item in condition.damage_items:
        key = ((item.location or "").strip().lower(), (item.type or "").strip().lower())
        raw = llm_damage_by_key.get(key)
        needed, urgency, acceptable, rationale = _classify_damage(
            item,
            asset_class,
            raw.repair_needed if raw else None,
            raw.repair_urgency if raw else None,
            raw.acceptable_wear if raw else None,
        )
        updated = item.model_copy(
            update={
                "repair_needed": needed,
                "repair_urgency": urgency,
                "acceptable_wear": acceptable,
                "repair_action": item.repair_action or rationale,
            }
        )
        updated_damage.append(updated)
        plan_items.append(
            RepairPlanItem(
                damage_type=item.type,
                location=item.location,
                repair_needed=needed,
                repair_urgency=urgency,
                acceptable_wear=acceptable,
                rationale=rationale,
            )
        )

    overall = any(
        p.repair_needed in (RepairNeeded.REQUIRED, RepairNeeded.RECOMMENDED) for p in plan_items
    )
    summary_parts = [p.rationale for p in plan_items if p.repair_needed != RepairNeeded.NONE][:3]
    summary = llm.repair_recommendation or llm.reasoning.repair_judgement_notes
    if summary_parts and not summary:
        summary = "; ".join(summary_parts)

    condition.damage_items = updated_damage
    condition.repair_plan = RepairPlan(
        overall_repair_needed=overall,
        summary=summary,
        items=plan_items,
    )
    if summary:
        condition.repair_recommendation = summary
    return condition.repair_plan
