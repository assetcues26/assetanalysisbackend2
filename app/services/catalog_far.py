"""Fixed Asset Register (FAR) depreciation for demo ERP catalog.

Uses straight-line method (SLM) with Companies Act Schedule II inspired useful lives,
5% residual/salvage value, and pro-rata age from acquisition date to the FAR as-of date.
"""

from __future__ import annotations

from datetime import date
from typing import Any

FAR_AS_OF_DATE = date(2026, 6, 7)
DEFAULT_RESIDUAL_PCT = 0.05

# Useful life in years (Schedule II / common Indian FAR practice).
USEFUL_LIFE_BY_SUBCATEGORY: dict[str, float] = {
    "split ac": 15.0,
    "window ac": 15.0,
    "laptop": 5.0,
    "desktop": 3.0,
    "printer": 5.0,
    "display": 5.0,
    "office chair": 10.0,
    "generator": 15.0,
    "water cooler": 8.0,
    "suv": 8.0,
}


def resolve_useful_life_years(item: dict[str, Any]) -> float:
    if item.get("useful_life_years") is not None:
        return float(item["useful_life_years"])
    sub = (item.get("subcategory") or "").lower()
    cat = (item.get("category") or "").lower()
    for key, life in USEFUL_LIFE_BY_SUBCATEGORY.items():
        if key in sub:
            return life
    if "laptop" in sub or "laptop" in cat or "it assets" in cat:
        return 5.0
    if "desktop" in sub or "desktop" in cat:
        return USEFUL_LIFE_BY_SUBCATEGORY["desktop"]
    if "hvac" in cat:
        return 15.0
    if "vehicle" in cat:
        return 8.0
    if "furniture" in cat:
        return 10.0
    if "industrial" in cat:
        return 15.0
    if "appliances" in cat:
        return 8.0
    return 5.0


def compute_slm_far(
    original_cost_inr: float,
    acquisition_date: date,
    useful_life_years: float,
    *,
    residual_pct: float = DEFAULT_RESIDUAL_PCT,
    as_of: date = FAR_AS_OF_DATE,
) -> dict[str, Any]:
    """Return FAR depreciation fields; book_nbv_inr = cost minus accumulated SLM (floored at salvage)."""
    if original_cost_inr <= 0:
        raise ValueError("original_cost_inr must be positive")
    if useful_life_years <= 0:
        raise ValueError("useful_life_years must be positive")

    age_years = max(0.0, (as_of - acquisition_date).days / 365.25)
    residual_inr = round(original_cost_inr * residual_pct, 2)
    depreciable = original_cost_inr - residual_inr
    annual_depreciation_inr = round(depreciable / useful_life_years, 2)
    years_charged = min(age_years, useful_life_years)
    raw_accumulated = min(depreciable, annual_depreciation_inr * age_years)
    book_nbv_inr = round(max(residual_inr, original_cost_inr - raw_accumulated))
    accumulated_depreciation_inr = round(original_cost_inr - book_nbv_inr, 2)

    return {
        "depreciation_method": "SLM",
        "useful_life_years": useful_life_years,
        "residual_value_pct": residual_pct,
        "residual_value_inr": residual_inr,
        "annual_depreciation_inr": annual_depreciation_inr,
        "depreciation_years_charged": round(years_charged, 2),
        "asset_age_years": round(age_years, 2),
        "accumulated_depreciation_inr": accumulated_depreciation_inr,
        "book_nbv_inr": book_nbv_inr,
        "far_as_of_date": as_of.isoformat(),
    }


def enrich_catalog_item(item: dict[str, Any], *, as_of: date = FAR_AS_OF_DATE) -> dict[str, Any]:
    """Merge SLM-derived FAR fields into a catalog row."""
    acq_raw = item.get("acquisition_date") or item.get("capitalization_date")
    if not acq_raw:
        raise ValueError(f"catalog item {item.get('catalog_id')} missing acquisition_date")
    acq = date.fromisoformat(str(acq_raw)[:10])
    cost = float(item["original_cost_inr"])
    life = resolve_useful_life_years(item)
    residual_pct = float(item.get("residual_value_pct", DEFAULT_RESIDUAL_PCT))
    far = compute_slm_far(cost, acq, life, residual_pct=residual_pct, as_of=as_of)

    out = {**item, **far}
    if item.get("nbv_locked") and item.get("book_nbv_inr") is not None:
        locked = round(float(item["book_nbv_inr"]), 2)
        out["book_nbv_inr"] = locked
        out["accumulated_depreciation_inr"] = round(cost - locked, 2)
    return out


def enrich_catalog(items: list[dict[str, Any]], *, as_of: date = FAR_AS_OF_DATE) -> list[dict[str, Any]]:
    return [enrich_catalog_item(item, as_of=as_of) for item in items]
