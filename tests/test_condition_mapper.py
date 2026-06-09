"""Unit tests for damage mapping (single-call)."""

from app.models.responses import LLMAnalysisResult, LLMDamageItem
from app.services.condition_mapper import (
    build_damage_items,
    damage_needs_review,
    merge_damage_sources,
)


def test_build_damage_with_placement():
    llm = LLMAnalysisResult(
        damage_items=[
            LLMDamageItem(
                location="top lid rear-left",
                type="dent",
                severity="moderate",
                seen_in_image=2,
                horizontal="left",
                in_frame_position="upper-left",
                detail="~1cm dent on corner.",
                affects_function=False,
                repair_action="Buff panel.",
            ),
        ],
    )
    items = build_damage_items(llm, images_analyzed=3)
    assert len(items) == 1
    assert items[0].placement is not None
    assert items[0].placement.seen_in_image == 2
    assert items[0].placement.horizontal == "left"


def test_merge_damage_from_functional_issues():
    llm = LLMAnalysisResult(
        damage_items=[],
        functional_issues=["bent hinge restricts opening"],
    )
    items = merge_damage_sources(llm, max_images=2)
    assert len(items) == 1
    assert items[0].type == "functional"


def test_damage_needs_review():
    llm = LLMAnalysisResult(
        damage_items=[],
        condition_summary="Visible scratch on the lid and a small dent.",
    )
    assert damage_needs_review(llm) is True

    llm_ok = LLMAnalysisResult(
        damage_items=[LLMDamageItem(location="lid", type="scratch", severity="minor")],
        condition_summary="Scratch on lid.",
    )
    assert damage_needs_review(llm_ok) is False


def test_damage_single_image_gets_seen_in_image_1():
    """When images_analyzed=1, all damage items should get seen_in_image=1."""
    llm = LLMAnalysisResult(
        damage_items=[
            LLMDamageItem(
                location="front panel",
                type="scratch",
                severity="minor",
                detail="Light scratch on the front.",
            ),
        ],
    )
    items = build_damage_items(llm, images_analyzed=1)
    assert len(items) == 1
    assert items[0].seen_in_image == 1


def test_damage_infers_image_from_detail_text():
    """Damage detail containing 'Image N' should infer seen_in_image."""
    llm = LLMAnalysisResult(
        damage_items=[
            LLMDamageItem(
                location="rear panel",
                type="dent",
                severity="moderate",
                detail="A small dent visible in Image 3.",
            ),
        ],
    )
    items = build_damage_items(llm, images_analyzed=4)
    assert len(items) == 1
    assert items[0].seen_in_image == 3


def test_damage_side_panel_uses_barcode_image():
    """Damage on 'side panel' should use barcode_seen_in_image when available."""
    llm = LLMAnalysisResult(
        barcode_seen_in_image=2,
        damage_items=[
            LLMDamageItem(
                location="right side panel",
                type="scratch",
                severity="minor",
                detail="Light scratch near label area.",
            ),
        ],
    )
    items = build_damage_items(llm, images_analyzed=3)
    assert len(items) == 1
    assert items[0].seen_in_image == 2
