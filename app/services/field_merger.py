"""Normalize Gemini analysis output into clean API models."""

import re

from app.config import Settings, get_settings
from app.models.responses import AssetDetails, LLMAnalysisResult
from app.services.age_parser import build_asset_age_display
from app.services.asset_description import resolve_asset_description

_TAG_DIGITS_RE = re.compile(r"^[0-9]+$")
_TAG_MIN_LEN = 8
_TAG_MAX_LEN = 20


def normalize_tag_number(tag: str | None, settings: Settings | None = None) -> str | None:
    if tag is None:
        return None
    cleaned = str(tag).strip().strip('"\'')
    if not cleaned or cleaned.upper() == "UNREADABLE":
        return None

    digits_only = re.sub(r"\D", "", cleaned)
    if digits_only and digits_only != cleaned.replace(" ", ""):
        cleaned = digits_only

    if not _TAG_DIGITS_RE.match(cleaned):
        return None
    if len(cleaned) < _TAG_MIN_LEN or len(cleaned) > _TAG_MAX_LEN:
        return None
    return cleaned


def _clean_list(items: list[str] | None, limit: int = 25) -> list[str]:
    seen: list[str] = []
    for item in items or []:
        text = str(item).strip()
        if text and text not in seen:
            seen.append(text)
        if len(seen) >= limit:
            break
    return seen


def to_asset_details(result: LLMAnalysisResult, settings: Settings | None = None) -> AssetDetails:
    settings = settings or get_settings()
    quantity = result.quantity if isinstance(result.quantity, int) and result.quantity > 0 else 1
    age = build_asset_age_display(result)
    return AssetDetails(
        name=result.asset_name,
        category=result.category,
        type=result.asset_type,
        brand=result.brand,
        model=result.model,
        color=result.color,
        material=result.material,
        estimated_dimensions=result.estimated_dimensions,
        estimated_model_years=age.model_years,
        estimated_age_years=age.age_years,
        age_as_of_year=age.as_of_year,
        estimated_age=age.age_years or age.model_years,
        quantity=quantity,
        serial_number=result.serial_number,
        asset_tag_number=normalize_tag_number(result.asset_tag_number, settings),
        specifications=_clean_list(result.specifications),
        accessories=_clean_list(result.accessories),
        distinguishing_features=_clean_list(result.distinguishing_features),
        description=resolve_asset_description(result),
    )
