"""ERP-style demo context for V6 isolated analysis."""

from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class DemoContext(BaseModel):
    catalog_id: str
    asset_name: str
    description: str = ""
    make: str = ""
    model: str = ""
    category: str = ""
    subcategory: str = ""
    acquisition_date: date
    original_cost_inr: float = Field(gt=0)
    book_nbv_inr: float = Field(ge=0)
    location: str
    asset_tag_number: Optional[str] = None
    asset_number: Optional[str] = None
    depreciation_method: Optional[str] = None
    useful_life_years: Optional[float] = None
    accumulated_depreciation_inr: Optional[float] = None
    annual_depreciation_inr: Optional[float] = None
    residual_value_inr: Optional[float] = None

    @field_validator("asset_name", "location")
    @classmethod
    def _strip_required(cls, value: str) -> str:
        text = (value or "").strip()
        if not text:
            raise ValueError("Field is required")
        return text


def infer_location_profile(location: str) -> str:
    """Map Indian city/region to a climate wear profile for valuation prompts."""
    loc = (location or "").lower()
    coastal = (
        "mumbai",
        "chennai",
        "kolkata",
        "goa",
        "kochi",
        "kerala",
        "visakhapatnam",
        "vizag",
        "puducherry",
    )
    dry_hot = ("delhi", "jaipur", "ahmedabad", "rajasthan", "gurgaon", "noida", "lucknow")
    humid_inland = ("kolkata", "bhubaneswar", "cuttack")
    if any(c in loc for c in coastal):
        if any(h in loc for h in humid_inland):
            return "humid_inland"
        return "coastal_humid"
    if any(d in loc for d in dry_hot):
        return "dry_hot_dust"
    return "moderate"
