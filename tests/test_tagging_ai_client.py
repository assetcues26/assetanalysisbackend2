"""Tests for Tagging AI client."""

import pytest

from app.services.tagging_ai_client import analyze_asset_with_tagging_ai
from app.config import Settings


@pytest.mark.asyncio
async def test_analyze_requires_at_least_one_image():
    settings = Settings(tagging_ai_api_url="https://example.com/analyze")
    with pytest.raises(ValueError, match="At least one image"):
        await analyze_asset_with_tagging_ai(settings, {"assetid": "AST-1"}, None, None)
