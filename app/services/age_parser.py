"""Parse and compute asset age from model years or legacy text."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from app.models.responses import AssetDetails, LLMAnalysisResult

_YEAR_RANGE_RE = re.compile(r"(20\d{2})\s*[-–]\s*(20\d{2})")
_SINGLE_YEAR_RE = re.compile(r"\b(20\d{2})\b")
_YEARS_AGO_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[-–]?\s*(\d+(?:\.\d+)?)?\s*years?", re.I)
_TILDE_YEARS_RE = re.compile(r"~\s*(\d+(?:\.\d+)?)\s*[-–]?\s*(\d+(?:\.\d+)?)?\s*years?", re.I)


@dataclass(frozen=True)
class AgeParseResult:
    years_min: float
    years_max: float
    source: str


@dataclass(frozen=True)
class AssetAgeDisplay:
    model_years: str | None
    age_years: str | None
    as_of_year: int | None
    parsed: AgeParseResult | None


def _current_year(now_year: int | None = None) -> int:
    return now_year or datetime.now(timezone.utc).year


def extract_model_year_bounds(
    *,
    estimated_model_year_min: int | None = None,
    estimated_model_year_max: int | None = None,
    estimated_age: str | None = None,
) -> tuple[int | None, int | None]:
    if estimated_model_year_min is not None:
        y_max = estimated_model_year_max if estimated_model_year_max is not None else estimated_model_year_min
        return min(estimated_model_year_min, y_max), max(estimated_model_year_min, y_max)

    if not estimated_age:
        return None, None

    raw = str(estimated_age).strip()
    if not raw or raw.lower() in ("unknown", "n/a", "na", "null"):
        return None, None

    year_range = _YEAR_RANGE_RE.search(raw)
    if year_range:
        y1, y2 = int(year_range.group(1)), int(year_range.group(2))
        return min(y1, y2), max(y1, y2)

    years = [int(y) for y in _SINGLE_YEAR_RE.findall(raw)]
    if len(years) >= 2:
        return min(years), max(years)
    if len(years) == 1:
        return years[0], years[0]

    return None, None


def age_from_model_years(
    year_min: int,
    year_max: int,
    *,
    now_year: int | None = None,
) -> AgeParseResult:
    current_year = _current_year(now_year)
    lo, hi = min(year_min, year_max), max(year_min, year_max)
    return AgeParseResult(
        years_min=max(0.0, current_year - hi),
        years_max=max(0.0, current_year - lo),
        source="model_year",
    )


def format_model_years(year_min: int, year_max: int) -> str:
    lo, hi = min(year_min, year_max), max(year_min, year_max)
    return str(lo) if lo == hi else f"{lo}–{hi}"


def format_age_years(parsed: AgeParseResult, *, now_year: int | None = None) -> str:
    current_year = _current_year(now_year)
    lo = int(round(parsed.years_min))
    hi = int(round(parsed.years_max))
    if lo == hi:
        return f"~{lo} year{'s' if lo != 1 else ''} (as of {current_year})"
    return f"~{lo}–{hi} years (as of {current_year})"


def parse_estimated_age(text: str | None, *, now_year: int | None = None) -> AgeParseResult | None:
    """Parse legacy combined estimated_age text. Model-year range beats years phrase."""
    if not text:
        return None
    raw = str(text).strip()
    if not raw or raw.lower() in ("unknown", "n/a", "na", "null"):
        return None

    current_year = _current_year(now_year)

    year_min, year_max = extract_model_year_bounds(estimated_age=raw)
    if year_min is not None and year_max is not None:
        return age_from_model_years(year_min, year_max, now_year=current_year)

    match = _YEARS_AGO_RE.search(raw) or _TILDE_YEARS_RE.search(raw)
    if match:
        lo = float(match.group(1))
        hi = float(match.group(2)) if match.group(2) else lo
        return AgeParseResult(years_min=min(lo, hi), years_max=max(lo, hi), source="years_phrase")

    return None


def resolve_asset_age(
    llm: LLMAnalysisResult,
    *,
    asset: AssetDetails | None = None,
    now_year: int | None = None,
) -> AgeParseResult | None:
    """Age for valuation/NBV: model years (visual evidence) beat valuation_inputs age hints."""
    current_year = _current_year(now_year)

    year_min, year_max = extract_model_year_bounds(
        estimated_model_year_min=llm.estimated_model_year_min,
        estimated_model_year_max=llm.estimated_model_year_max,
        estimated_age=llm.estimated_age,
    )
    if year_min is not None and year_max is not None:
        return age_from_model_years(year_min, year_max, now_year=current_year)

    if llm.valuation_inputs and llm.valuation_inputs.age_years_min is not None:
        lo = float(llm.valuation_inputs.age_years_min)
        hi = float(
            llm.valuation_inputs.age_years_max
            if llm.valuation_inputs.age_years_max is not None
            else llm.valuation_inputs.age_years_min
        )
        return AgeParseResult(years_min=min(lo, hi), years_max=max(lo, hi), source="valuation_inputs")

    parsed = parse_estimated_age(llm.estimated_age, now_year=current_year)
    if parsed is not None:
        return parsed

    if asset is not None:
        year_min, year_max = extract_model_year_bounds(estimated_age=asset.estimated_model_years)
        if year_min is not None and year_max is not None:
            return age_from_model_years(year_min, year_max, now_year=current_year)
        if asset.estimated_age_years:
            return parse_estimated_age(asset.estimated_age_years, now_year=current_year)

    return None


def build_asset_age_display(
    llm: LLMAnalysisResult,
    *,
    now_year: int | None = None,
) -> AssetAgeDisplay:
    """Separate UI fields: model year vs age in years (computed from today)."""
    current_year = _current_year(now_year)
    year_min, year_max = extract_model_year_bounds(
        estimated_model_year_min=llm.estimated_model_year_min,
        estimated_model_year_max=llm.estimated_model_year_max,
        estimated_age=llm.estimated_age,
    )

    if year_min is not None and year_max is not None:
        parsed = age_from_model_years(year_min, year_max, now_year=current_year)
        return AssetAgeDisplay(
            model_years=format_model_years(year_min, year_max),
            age_years=format_age_years(parsed, now_year=current_year),
            as_of_year=current_year,
            parsed=parsed,
        )

    parsed = parse_estimated_age(llm.estimated_age, now_year=current_year)
    if parsed is None:
        return AssetAgeDisplay(None, None, None, None)

    if parsed.source == "years_phrase":
        return AssetAgeDisplay(
            model_years=None,
            age_years=format_age_years(parsed, now_year=current_year),
            as_of_year=current_year,
            parsed=parsed,
        )

    return AssetAgeDisplay(None, None, None, parsed)


def midpoint_years(parsed: AgeParseResult | None) -> float | None:
    if parsed is None:
        return None
    return round((parsed.years_min + parsed.years_max) / 2, 2)
