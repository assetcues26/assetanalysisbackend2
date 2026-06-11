"""Tests for capture session market region resolution."""

from app.services.capture_session_repository import resolve_session_market_region


def test_resolve_session_market_region_prefers_stored():
    row = {"market_region": "US"}
    assert resolve_session_market_region(row, "IN") == "US"


def test_resolve_session_market_region_falls_back_to_client():
    row = {}
    assert resolve_session_market_region(row, "GB") == "GB"


def test_resolve_session_market_region_defaults_to_in():
    row = {"market_region": "XX"}
    assert resolve_session_market_region(row, None) == "IN"


def test_resolve_session_market_region_uses_env_default():
    row = {}
    assert resolve_session_market_region(row, None, default_region="US") == "US"
