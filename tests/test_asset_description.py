"""Asset description fallback when LLM omits the dedicated field."""

from app.models.responses import LLMAnalysisResult, LLMReasoningTrace
from app.services.asset_description import resolve_asset_description
from app.services.field_merger import to_asset_details


def test_uses_llm_description_when_present():
    llm = LLMAnalysisResult(
        asset_name="AC",
        description="White split AC unit with front grille and brand badge.",
    )
    assert resolve_asset_description(llm) == "White split AC unit with front grille and brand badge."


def test_falls_back_to_condition_summary():
    llm = LLMAnalysisResult(
        asset_name="Micromax AC",
        brand="Micromax",
        category="HVAC",
        color="White",
        condition_summary="Unit shows moderate wear on the cabinet with intact grille.",
    )
    desc = resolve_asset_description(llm)
    assert desc is not None
    assert "Micromax" in desc
    assert "moderate wear" in desc


def test_to_asset_details_includes_synthesized_description():
    llm = LLMAnalysisResult(
        asset_name="Office chair",
        brand="Featherlite",
        category="Furniture",
        color="Black",
        condition_summary="Mesh back with adjustable armrests; light scuffing on base.",
    )
    asset = to_asset_details(llm)
    assert asset.description
    assert "Featherlite" in asset.description
    assert "scuffing" in asset.description
