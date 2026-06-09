"""Tests for tag crop hint heuristics."""

from app.models.responses import PlacementInfo
from app.pipeline.tag_crop import crop_hint_from_placement, frame_position_to_crop_hint


def test_lower_right_crop_hint():
    hint = frame_position_to_crop_hint("lower-right", image_index=2)
    assert hint is not None
    assert hint.image_index == 2
    assert hint.x_pct >= 40
    assert hint.y_pct >= 40
    assert hint.width_pct == 50.0


def test_bottom_right_alias():
    hint = frame_position_to_crop_hint("bottom right")
    assert hint is not None
    assert hint.x_pct >= 40
    assert hint.y_pct >= 40


def test_upper_left_crop_hint():
    hint = frame_position_to_crop_hint("upper-left")
    assert hint is not None
    assert hint.x_pct < 50
    assert hint.y_pct < 50


def test_horizontal_vertical_override():
    hint = frame_position_to_crop_hint(None, horizontal="left", vertical="top")
    assert hint is not None
    assert hint.x_pct < 50
    assert hint.y_pct < 50


def test_unknown_position_returns_none():
    assert frame_position_to_crop_hint(None) is None
    assert frame_position_to_crop_hint("") is None


def test_crop_hint_from_placement():
    placement = PlacementInfo(
        seen_in_image=3,
        in_frame_position="lower-right",
        horizontal="right",
        vertical="bottom",
    )
    hint = crop_hint_from_placement(placement)
    assert hint is not None
    assert hint.image_index == 3
