"""Live USD->target-currency exchange rates with in-process cache and safe fallback."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

import httpx
import structlog

from app.config import Settings

logger = structlog.get_logger()

FxTarget = Literal["INR", "USD", "GBP"]

_cache: dict[str, dict] = {}


@dataclass
class FxResult:
    rate: float
    source: str
    is_fallback: bool
    as_of: str | None = None
    target: str = "INR"


def _fallback_rate(settings: Settings, target: FxTarget) -> float:
    if target == "USD":
        return 1.0
    if target == "GBP":
        return settings.usd_to_gbp_fallback
    return settings.usd_to_inr_fallback


async def get_fx_rate(settings: Settings, target: FxTarget) -> FxResult:
    """Return USD->target rate. USD returns 1.0 without an API call."""
    if target == "USD":
        return FxResult(1.0, "identity", False, None, target)

    if not settings.fx_enabled:
        return FxResult(
            _fallback_rate(settings, target),
            "configured_fixed_rate",
            True,
            None,
            target,
        )

    now = time.time()
    cached = _cache.get(target)
    if cached and cached.get("rate") and (now - cached["ts"]) < settings.fx_cache_ttl_seconds:
        return FxResult(cached["rate"], cached["source"], False, cached.get("as_of"), target)

    try:
        async with httpx.AsyncClient(
            timeout=settings.fx_timeout_seconds, follow_redirects=True
        ) as client:
            resp = await client.get(
                settings.fx_api_url, params={"from": "USD", "to": target}
            )
            resp.raise_for_status()
            data = resp.json()
            rate = float(data["rates"][target])
            as_of = data.get("date")
        _cache[target] = {"rate": rate, "ts": now, "source": "frankfurter.app", "as_of": as_of}
        return FxResult(rate, "frankfurter.app", False, as_of, target)
    except Exception as exc:
        logger.warning("fx_fetch_failed", target=target, error=str(exc))
        if cached and cached.get("rate"):
            return FxResult(
                cached["rate"],
                f"{cached['source']}(stale)",
                False,
                cached.get("as_of"),
                target,
            )
        return FxResult(_fallback_rate(settings, target), "config_fallback", True, None, target)


async def get_usd_to_inr(settings: Settings) -> FxResult:
    """Backward-compatible wrapper for cost breakdown and legacy callers."""
    result = await get_fx_rate(settings, "INR")
    return result
