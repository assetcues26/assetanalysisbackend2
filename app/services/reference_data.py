"""Load valuation reference tables (prices, depreciation, rules) from configurable path."""

from __future__ import annotations

import json
from pathlib import Path

from app.config import Settings, get_settings
from app.markets.registry import resolve_market

_cache: dict[str, dict] = {}


def _default_data_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "data"


def resolve_reference_path(settings: Settings | None = None, market_region: str = "IN") -> Path:
    settings = settings or get_settings()
    raw = (settings.reference_prices_path or "").strip()
    if raw:
        return Path(raw)
    market = resolve_market(market_region, settings)
    return _default_data_dir() / market.reference_filename


def load_reference_data(settings: Settings | None = None, market_region: str = "IN") -> dict:
    """Cached JSON load; invalidates when file mtime changes."""
    settings = settings or get_settings()
    path = resolve_reference_path(settings, market_region)
    if not path.is_file():
        raise FileNotFoundError(f"Reference prices file not found: {path}")

    cache_key = str(path)
    mtime = path.stat().st_mtime
    cached = _cache.get(cache_key)
    if cached and cached.get("mtime") == mtime:
        return cached["data"]

    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)

    _cache[cache_key] = {"mtime": mtime, "data": data}
    return data


def valuation_rules(data: dict | None = None, settings: Settings | None = None, market_region: str = "IN") -> dict:
    data = data or load_reference_data(settings, market_region)
    rules = data.get("valuation_rules") or {}
    return {
        "severity_multipliers": rules.get(
            "severity_multipliers",
            {"minor": 0.98, "moderate": 0.90, "severe": 0.75, "unknown": 0.95},
        ),
        "as_is_band_pct": float(rules.get("as_is_band_pct", 0.08)),
        "nbv_band_pct": float(rules.get("nbv_band_pct", 0.06)),
        "functional_issues_multiplier": float(rules.get("functional_issues_multiplier", 0.85)),
        "min_condition_score_factor": float(rules.get("min_condition_score_factor", 0.5)),
        "min_condition_multiplier": float(rules.get("min_condition_multiplier", 0.25)),
        "max_condition_multiplier": float(rules.get("max_condition_multiplier", 1.0)),
        "age_multiplier_when_unknown": float(rules.get("age_multiplier_when_unknown", 0.85)),
        "min_age_multiplier": float(rules.get("min_age_multiplier", 0.35)),
        "like_new_hint_band_pct": float(rules.get("like_new_hint_band_pct", 0.05)),
        "as_is_floor_ratio": float(rules.get("as_is_floor_ratio", 0.92)),
        "weak_identity_confidence_cap": float(rules.get("weak_identity_confidence_cap", 0.45)),
        "generation_ambiguous_confidence_cap": float(rules.get("generation_ambiguous_confidence_cap", 0.65)),
        "missing_age_confidence_cap": float(rules.get("missing_age_confidence_cap", 0.6)),
        "default_valuation_confidence": float(rules.get("default_valuation_confidence", 0.7)),
    }


def category_segment_keywords(data: dict | None = None, settings: Settings | None = None, market_region: str = "IN") -> dict[str, list[str]]:
    data = data or load_reference_data(settings, market_region)
    return data.get("category_segment_keywords") or {}


def reference_data_label(settings: Settings | None = None, market_region: str = "IN") -> str:
    return resolve_reference_path(settings, market_region).name
