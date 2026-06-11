"""Settings market_region env normalization."""

from app.config import Settings


def test_market_region_from_env():
    settings = Settings(market_region="us")
    assert settings.market_region == "US"


def test_market_region_invalid_falls_back_to_in():
    settings = Settings(market_region="EU")
    assert settings.market_region == "IN"
