"""Market region registry — IN / US / GB."""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings

SUPPORTED_REGIONS = frozenset({"IN", "US", "GB"})


@dataclass(frozen=True)
class MarketConfig:
    region: str
    currency: str
    default_locale: str
    reference_filename: str
    fx_target: str
    currency_symbol: str
    market_label: str


_MARKETS: dict[str, MarketConfig] = {
    "IN": MarketConfig(
        region="IN",
        currency="INR",
        default_locale="en-IN",
        reference_filename="reference_prices_IN.json",
        fx_target="INR",
        currency_symbol="₹",
        market_label="India",
    ),
    "US": MarketConfig(
        region="US",
        currency="USD",
        default_locale="en-US",
        reference_filename="reference_prices_US.json",
        fx_target="USD",
        currency_symbol="$",
        market_label="United States",
    ),
    "GB": MarketConfig(
        region="GB",
        currency="GBP",
        default_locale="en-GB",
        reference_filename="reference_prices_GB.json",
        fx_target="GBP",
        currency_symbol="£",
        market_label="United Kingdom",
    ),
}


def resolve_market(region: str | None, settings: Settings) -> MarketConfig:
    """Resolve market region; falls back to Settings.market_region (MARKET_REGION env)."""
    if not settings.multi_market_enabled:
        return _MARKETS["IN"]
    raw = (region or settings.market_region or "IN").strip().upper()
    if raw not in SUPPORTED_REGIONS:
        return _MARKETS["IN"]
    return _MARKETS[raw]


def default_market_region(settings: Settings) -> str:
    """App-wide default region from MARKET_REGION env."""
    return resolve_market(None, settings).region


def build_gemini_market_prompt(market: MarketConfig) -> str:
    """Market-specific valuation instructions for Gemini."""
    if market.region == "US":
        return (
            "\n\nCLIENT MARKET: United States. All valuation reasoning must reflect typical US "
            "retail and used-asset prices (national averages, major metros). Client-facing amounts "
            "are shown in USD ($) — reason about value in US dollars first, then map internal "
            "reference_like_new_usd hints consistently."
        )
    if market.region == "GB":
        return (
            "\n\nCLIENT MARKET: United Kingdom. All valuation reasoning must reflect typical UK "
            "retail and used-asset prices (England, Scotland, Wales). Client-facing amounts "
            "are shown in GBP (£) — reason about value in pounds first, then map internal "
            "reference_like_new_usd hints consistently."
        )
    return (
        "\n\nCLIENT MARKET: India. All valuation reasoning must reflect typical India retail "
        "and used-asset prices (metros and tier-2 cities). Client-facing amounts are shown in "
        "INR (₹) only — reason about value in rupees first, then map internal hints consistently."
    )


def currency_note_for_market(market: MarketConfig) -> str:
    names = {"INR": "Indian Rupees (₹)", "USD": "US Dollars ($)", "GBP": "British Pounds (£)"}
    label = names.get(market.currency, market.currency)
    return f"All amounts in {label}, estimated for the {market.market_label} market."
