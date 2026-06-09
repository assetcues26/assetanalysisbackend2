"""Unit tests for identifier placement mapping (single-call)."""

from app.models.responses import LLMAnalysisResult, LLMStickerItem
from app.services.placement_mapper import (
    build_identifiers,
    enrich_llm_sticker_labels,
    identifiers_need_review,
    merge_sticker_sources,
    parse_barcode_position_text,
    stickers_image_index_need_review,
)
from app.services.condition_mapper import stickers_need_review


def test_parse_barcode_position_text():
    placement = parse_barcode_position_text("right side panel, Image 2", max_images=3)
    assert placement.seen_in_image == 2
    assert placement.horizontal == "right"


def test_build_identifiers_structured():
    detailed_phrase = (
        "Lower-right of the base panel, on a white printed sticker below the spec "
        "plate, about 4 cm from the bottom edge, bars horizontal — visible in Image 3."
    )
    llm = LLMAnalysisResult(
        asset_tag_number="1234567890123456",
        tag_readable=True,
        barcode_present=True,
        barcode_asset_location="base panel",
        barcode_horizontal="right",
        barcode_seen_in_image=3,
        barcode_in_frame_position="lower-right",
        barcode_position=detailed_phrase,
        tag_detection_reasoning="Clear barcode on base.",
        stickers=[
            LLMStickerItem(
                label_text="Dell",
                sticker_type="brand",
                asset_location="lid",
                horizontal="center",
                seen_in_image=1,
            ),
        ],
        visible_labels=["Dell"],
    )
    ids = build_identifiers(llm, "1234567890123456", images_analyzed=3)

    assert ids.tag_position == detailed_phrase
    assert ids.tag_detection_reasoning == "Clear barcode on base."
    assert ids.barcode.placement.seen_in_image == 3
    assert ids.barcode.placement.horizontal == "right"
    assert ids.barcode.placement.description == detailed_phrase
    assert len(ids.stickers) == 1


def test_barcode_placement_description_falls_back_to_structured_phrase():
    llm = LLMAnalysisResult(
        asset_tag_number="1234567890123456",
        tag_readable=True,
        barcode_present=True,
        barcode_asset_location="right side panel",
        barcode_horizontal="right",
        barcode_vertical="bottom",
        barcode_seen_in_image=2,
        barcode_in_frame_position="bottom right",
    )
    ids = build_identifiers(llm, "1234567890123456", images_analyzed=3)
    assert ids.barcode.placement.description is not None
    assert "right side panel" in ids.barcode.placement.description
    assert "Image 2" in ids.barcode.placement.description


def test_enrich_stickers_from_specifications():
    llm = LLMAnalysisResult(
        specifications=["PM 0.3", "PM 2.5"],
        distinguishing_features=["Breathe Pure branding"],
        description="Labels on the side panel include filter ratings.",
        stickers=[
            LLMStickerItem(
                label_text="Q.C. PASS",
                sticker_type="other",
                asset_location="right side panel",
                horizontal="right",
                vertical="top",
                seen_in_image=2,
                in_frame_position="top right",
            ),
        ],
    )
    enriched = enrich_llm_sticker_labels(llm, images_analyzed=3)
    ids = build_identifiers(enriched, None, images_analyzed=3)
    pm = next(s for s in ids.stickers if s.label_text == "PM 0.3")
    assert pm.placement is not None
    assert pm.placement.horizontal == "right"
    assert pm.placement.asset_location is not None
    assert pm.placement.seen_in_image == 2


def test_merge_sticker_sources_unions_partial_gemini_output():
    llm = LLMAnalysisResult(
        stickers=[LLMStickerItem(label_text="Dell", sticker_type="brand")],
        specifications=["R32 refrigerant", "16GB RAM"],
        distinguishing_features=["Latitude badge"],
    )
    merged = merge_sticker_sources(llm, images_analyzed=3)
    labels = {s.label_text for s in merged.stickers}
    assert "Dell" in labels
    assert "R32 refrigerant" in labels
    assert "16GB RAM" in labels
    assert "Latitude badge" in labels
    assert stickers_need_review(merged) is False


def test_identifiers_need_review_when_placement_missing():
    llm = LLMAnalysisResult(asset_tag_number="100301912005536", tag_readable=True)
    assert identifiers_need_review(llm, "100301912005536", 3) is True

    llm2 = LLMAnalysisResult(
        barcode_position="side panel, Image 2",
        barcode_seen_in_image=2,
    )
    assert identifiers_need_review(llm2, "100301912005536", 3) is False


def test_no_fake_detection_reasoning():
    llm = LLMAnalysisResult(asset_tag_number="100301912005536", tag_readable=True)
    ids = build_identifiers(llm, "100301912005536", images_analyzed=3)
    assert ids.tag_detection_reasoning is None
    assert ids.barcode.detection_reasoning is None


def test_backfill_side_specs_use_barcode_image_not_template():
    llm = LLMAnalysisResult(
        barcode_seen_in_image=2,
        barcode_position="Right side panel, Image 2",
        stickers=[
            LLMStickerItem(
                label_text="5 Years Comprehensive Warranty",
                sticker_type="warranty",
                asset_location="top left",
                horizontal="left",
                vertical="top",
                seen_in_image=3,
                in_frame_position="top left",
            ),
            LLMStickerItem(
                label_text="Q.C. PASS",
                sticker_type="other",
                asset_location="right side panel",
                horizontal="right",
                vertical="top",
                seen_in_image=2,
                in_frame_position="top right",
            ),
        ],
        specifications=["PM 0.3", "PM 2.5"],
    )
    merged = merge_sticker_sources(llm, images_analyzed=4)
    by_label = {s.label_text: s.seen_in_image for s in merged.stickers}
    assert by_label["PM 0.3"] == 2
    assert by_label["PM 2.5"] == 2
    assert by_label["Q.C. PASS"] == 2


def test_harmonize_corrects_gemini_side_spec_wrong_index():
    llm = LLMAnalysisResult(
        barcode_seen_in_image=2,
        stickers=[
            LLMStickerItem(
                label_text="PM 0.3",
                sticker_type="spec",
                asset_location="side panel",
                horizontal="right",
                seen_in_image=3,
            ),
            LLMStickerItem(
                label_text="Q.C. PASS",
                sticker_type="other",
                asset_location="right side panel",
                seen_in_image=2,
            ),
        ],
    )
    merged = merge_sticker_sources(llm, images_analyzed=3)
    pm = next(s for s in merged.stickers if s.label_text == "PM 0.3")
    assert pm.seen_in_image == 2


def test_clamp_invalid_seen_in_image():
    llm = LLMAnalysisResult(
        stickers=[
            LLMStickerItem(
                label_text="PM 0.3",
                sticker_type="spec",
                asset_location="side panel",
                seen_in_image=9,
            ),
        ],
    )
    merged = merge_sticker_sources(llm, images_analyzed=3)
    assert merged.stickers[0].seen_in_image is None


def test_front_stickers_get_seen_in_image_when_gemini_omits():
    llm = LLMAnalysisResult(
        barcode_seen_in_image=2,
        description="White AC with digital temperature display on the front panel.",
        stickers=[
            LLMStickerItem(
                label_text="Quad Air Protection",
                sticker_type="spec",
                asset_location="Top front left",
                horizontal="left",
                vertical="top",
                in_frame_position="top left",
            ),
            LLMStickerItem(
                label_text="Breathe Pure branding",
                sticker_type="brand",
                asset_location="front panel",
                horizontal="right",
                vertical="top",
                in_frame_position="top right",
            ),
            LLMStickerItem(
                label_text="Digital temperature display on front panel",
                sticker_type="brand",
                asset_location="front panel",
                horizontal="center",
                vertical="center",
                in_frame_position="top left",
            ),
        ],
    )
    merged = merge_sticker_sources(llm, images_analyzed=4)
    for label in (
        "Quad Air Protection",
        "Breathe Pure branding",
        "Digital temperature display on front panel",
    ):
        item = next(s for s in merged.stickers if s.label_text == label)
        assert item.seen_in_image == 1, label
    ids = build_identifiers(merged, "100301912005536", images_analyzed=4)
    quad = next(s for s in ids.stickers if s.label_text == "Quad Air Protection")
    assert quad.placement.seen_in_image == 1


def test_stickers_image_index_need_review_on_panel_mismatch():
    stickers = [
        LLMStickerItem(
            label_text="PM 0.3",
            asset_location="side panel",
            seen_in_image=2,
        ),
        LLMStickerItem(
            label_text="PM 2.5",
            asset_location="side panel",
            seen_in_image=3,
        ),
    ]
    assert stickers_image_index_need_review(stickers, max_images=4) is True


def test_single_image_all_stickers_get_seen_in_image_1():
    """When images_analyzed=1, ALL stickers must get seen_in_image=1, never null."""
    llm = LLMAnalysisResult(
        specifications=["PM 0.3", "PM 2.5", "VOC Filter"],
        distinguishing_features=["Digital temperature display"],
        stickers=[
            LLMStickerItem(
                label_text="BREATHE PURE",
                sticker_type="brand",
                asset_location="front panel",
                horizontal="right",
                vertical="top",
            ),
        ],
    )
    merged = merge_sticker_sources(llm, images_analyzed=1)
    for s in merged.stickers:
        assert s.seen_in_image == 1, f"{s.label_text} has seen_in_image={s.seen_in_image}"


def test_side_panel_stickers_null_index_when_no_barcode():
    """Side-panel stickers should still get seen_in_image from harmonization when
    barcode_seen_in_image is null but max_images=1."""
    llm = LLMAnalysisResult(
        stickers=[
            LLMStickerItem(
                label_text="PM 0.3",
                sticker_type="spec",
                asset_location="side panel",
                horizontal="right",
                vertical="top",
                in_frame_position="top right",
            ),
        ],
    )
    merged = merge_sticker_sources(llm, images_analyzed=1)
    pm = next(s for s in merged.stickers if s.label_text == "PM 0.3")
    assert pm.seen_in_image == 1


def test_out_of_range_index_uses_panel_target():
    """When LLM returns out-of-range index for a side-panel sticker, use the
    canonical side panel image instead of null."""
    llm = LLMAnalysisResult(
        barcode_seen_in_image=2,
        stickers=[
            LLMStickerItem(
                label_text="PM 0.3",
                sticker_type="spec",
                asset_location="side panel",
                horizontal="right",
                seen_in_image=9,
            ),
        ],
    )
    merged = merge_sticker_sources(llm, images_analyzed=3)
    pm = next(s for s in merged.stickers if s.label_text == "PM 0.3")
    assert pm.seen_in_image == 2


def test_barcode_present_false_for_unreadable_tag():
    """When asset_tag_number is UNREADABLE and no other barcode evidence exists,
    barcode_present should be False."""
    llm = LLMAnalysisResult(
        asset_tag_number="UNREADABLE",
        barcode_present=False,
    )
    ids = build_identifiers(llm, None, images_analyzed=1)
    assert ids.barcode.present is False
    assert ids.tag_readable is False


def test_tag_not_readable_without_tag_number():
    """Model flag alone must not mark a readable tag when no digits are present."""
    llm = LLMAnalysisResult(
        tag_readable=True,
        barcode_present=True,
        barcode_position="side panel, Image 1",
    )
    ids = build_identifiers(llm, None, images_analyzed=1)
    assert ids.tag_readable is False
    assert ids.barcode.present is False
