"""Human-readable age strings (years + months)."""

from __future__ import annotations


def format_age_years_months(years: float | None) -> str:
    """Format decimal years as 'X years Y months' (rounded to nearest month)."""
    if years is None:
        return "—"
    total_months = max(0, round(float(years) * 12))
    y, m = divmod(total_months, 12)
    if y == 0:
        return f"{m} month{'s' if m != 1 else ''}"
    if m == 0:
        return f"{y} year{'s' if y != 1 else ''}"
    return f"{y} year{'s' if y != 1 else ''} {m} month{'s' if m != 1 else ''}"
