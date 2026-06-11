"""Shared market fixtures for valuation tests."""

from app.config import Settings
from app.markets.registry import resolve_market

IN_MARKET = resolve_market("IN", Settings())
US_MARKET = resolve_market("US", Settings())
GB_MARKET = resolve_market("GB", Settings())
