"""Live USD->INR exchange rate with in-process cache and safe fallback."""

import time
from dataclasses import dataclass

import httpx
import structlog

from app.config import Settings

logger = structlog.get_logger()


@dataclass
class FxResult:
    rate: float
    source: str
    is_fallback: bool
    as_of: str | None = None


_cache: dict = {"rate": None, "ts": 0.0, "source": None, "as_of": None}


async def get_usd_to_inr(settings: Settings) -> FxResult:
    """Return a live USD->INR rate, cached for fx_cache_ttl_seconds, with fallback."""
    if not settings.fx_enabled:
        return FxResult(
            settings.usd_to_inr_fallback,
            "configured_fixed_rate",
            True,
            None,
        )

    now = time.time()
    if _cache["rate"] and (now - _cache["ts"]) < settings.fx_cache_ttl_seconds:
        return FxResult(_cache["rate"], _cache["source"], False, _cache["as_of"])

    try:
        async with httpx.AsyncClient(
            timeout=settings.fx_timeout_seconds, follow_redirects=True
        ) as client:
            resp = await client.get(
                settings.fx_api_url, params={"from": "USD", "to": "INR"}
            )
            resp.raise_for_status()
            data = resp.json()
            rate = float(data["rates"]["INR"])
            as_of = data.get("date")
        _cache.update(rate=rate, ts=now, source="frankfurter.app", as_of=as_of)
        return FxResult(rate, "frankfurter.app", False, as_of)
    except Exception as exc:
        logger.warning("fx_fetch_failed", error=str(exc))
        if _cache["rate"]:
            return FxResult(_cache["rate"], f"{_cache['source']}(stale)", False, _cache["as_of"])
        return FxResult(settings.usd_to_inr_fallback, "config_fallback", True)
