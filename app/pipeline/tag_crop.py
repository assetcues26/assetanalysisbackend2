"""Heuristic tag-region crop hints from barcode placement metadata (display-only)."""

from __future__ import annotations

import re

from app.models.responses import PlacementInfo, TagZoomHint

_POSITION_ALIASES: dict[str, tuple[str, str]] = {
    "lower-right": ("right", "bottom"),
    "lower right": ("right", "bottom"),
    "bottom right": ("right", "bottom"),
    "bottom-right": ("right", "bottom"),
    "lower-left": ("left", "bottom"),
    "lower left": ("left", "bottom"),
    "bottom left": ("left", "bottom"),
    "bottom-left": ("left", "bottom"),
    "upper-right": ("right", "top"),
    "upper right": ("right", "top"),
    "top right": ("right", "top"),
    "top-right": ("right", "top"),
    "upper-left": ("left", "top"),
    "upper left": ("left", "top"),
    "top left": ("left", "top"),
    "top-left": ("left", "top"),
    "lower-center": ("center", "bottom"),
    "lower center": ("center", "bottom"),
    "bottom center": ("center", "bottom"),
    "bottom-center": ("center", "bottom"),
    "upper-center": ("center", "top"),
    "upper center": ("center", "top"),
    "top center": ("center", "top"),
    "top-center": ("center", "top"),
    "center": ("center", "center"),
    "middle": ("center", "center"),
}

_HORIZ = frozenset({"left", "center", "right"})
_VERT = frozenset({"top", "center", "bottom"})
_BOX_SIZE = 0.50


def _normalize_position(raw: str | None) -> tuple[str, str] | None:
    if not raw:
        return None
    key = re.sub(r"\s+", " ", raw.strip().lower())
    if key in _POSITION_ALIASES:
        return _POSITION_ALIASES[key]
    parts = key.replace("-", " ").split()
    if len(parts) >= 2:
        v, h = parts[0], parts[-1]
        if v in ("upper", "top"):
            v = "top"
        elif v in ("lower", "bottom"):
            v = "bottom"
        if h in ("left", "right", "center") and v in ("top", "bottom", "center"):
            return (h, v)
    return None


def _axis_start(align: str, size: float) -> float:
    if align == "left" or align == "top":
        return 0.05
    if align == "right" or align == "bottom":
        return max(0.0, 1.0 - size - 0.05)
    return (1.0 - size) / 2


def frame_position_to_crop_hint(
    in_frame_position: str | None,
    horizontal: str | None = None,
    vertical: str | None = None,
    *,
    image_index: int | None = None,
) -> TagZoomHint | None:
    """Map placement text to a percentage bounding box for UI zoom."""
    h_align, v_align = None, None
    parsed = _normalize_position(in_frame_position)
    if parsed:
        h_align, v_align = parsed
    if horizontal and str(horizontal).strip().lower() in _HORIZ:
        h_align = str(horizontal).strip().lower()
    if vertical and str(vertical).strip().lower() in _VERT:
        v_align = str(vertical).strip().lower()
    if not h_align and not v_align:
        return None
    h_align = h_align or "center"
    v_align = v_align or "center"
    size = _BOX_SIZE
    return TagZoomHint(
        image_index=image_index,
        x_pct=round(_axis_start(h_align, size) * 100, 1),
        y_pct=round(_axis_start(v_align, size) * 100, 1),
        width_pct=round(size * 100, 1),
        height_pct=round(size * 100, 1),
    )


def crop_hint_from_placement(
    placement: PlacementInfo | None,
    *,
    fallback_image_index: int | None = None,
) -> TagZoomHint | None:
    if not placement:
        return None
    idx = placement.seen_in_image or fallback_image_index
    hint = frame_position_to_crop_hint(
        placement.in_frame_position,
        placement.horizontal,
        placement.vertical,
        image_index=idx,
    )
    if hint and hint.image_index is None and idx is not None:
        return hint.model_copy(update={"image_index": idx})
    return hint
