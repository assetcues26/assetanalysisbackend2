"""Map LLM identifier fields into API identifiers (single Gemini call + same-response enrich)."""

import re

from app.models.responses import (
    BarcodeDetails,
    Identifiers,
    LLMAnalysisResult,
    LLMStickerItem,
    PlacementInfo,
    StickerItem,
)
from app.services.field_merger import _clean_list

_HORIZONTAL = frozenset({"left", "center", "right"})
_VERTICAL = frozenset({"top", "center", "bottom"})
_STICKER_TYPES = frozenset(
    {"company", "brand", "rating", "warranty", "spec", "other"}
)
_IMAGE_NUM_RE = re.compile(r"\bimage\s*(\d+)\b", re.IGNORECASE)
_FRONT_IMAGE_RE = re.compile(
    r"front[^.]{0,120}?\bimage\s*(\d+)\b|\bimage\s*(\d+)\b[^.]{0,120}?front",
    re.IGNORECASE,
)
_QUOTED_RE = re.compile(r"['\"]([^'\"]{2,60})['\"]")
_BRANDING_RE = re.compile(r"(\w[\w\s]{1,40})\s+branding", re.IGNORECASE)
_PANEL_HINTS = (
    ("side panel", "side panel"),
    ("right side", "right side panel"),
    ("left side", "left side panel"),
    ("front panel", "front panel"),
    ("rear panel", "rear panel"),
    ("back panel", "back panel"),
    ("base panel", "base panel"),
    ("bottom panel", "bottom panel"),
    ("top panel", "top panel"),
)
_MAX_STICKERS = 30
_SIDE_SPEC_KEYWORDS = (
    "pm 0.3",
    "pm 2.5",
    "pm ",
    "filter",
    "r32",
    "refrigerant",
    "warning",
    "qc",
    "vgc",
    "bee",
    "rating",
    "spec",
)


def _norm_enum(value: str | None, allowed: frozenset[str]) -> str | None:
    if not value:
        return None
    key = str(value).strip().lower()
    return key if key in allowed else None


def _clamp_image_index(value: int | None, max_images: int) -> int | None:
    if not isinstance(value, int) or max_images < 1:
        return None
    if 1 <= value <= max_images:
        return value
    return None


def placement_from_parts(
    *,
    asset_location: str | None,
    horizontal: str | None,
    vertical: str | None,
    seen_in_image: int | None,
    in_frame_position: str | None,
    max_images: int,
    description: str | None = None,
) -> PlacementInfo | None:
    placement = PlacementInfo(
        asset_location=(asset_location or "").strip() or None,
        horizontal=_norm_enum(horizontal, _HORIZONTAL),
        vertical=_norm_enum(vertical, _VERTICAL),
        seen_in_image=_clamp_image_index(seen_in_image, max_images),
        in_frame_position=(in_frame_position or "").strip() or None,
        description=(description or "").strip() or None,
    )
    if not any(
        [
            placement.asset_location,
            placement.horizontal,
            placement.vertical,
            placement.seen_in_image,
            placement.in_frame_position,
            placement.description,
        ]
    ):
        return None
    return placement


def parse_barcode_position_text(
    text: str | None,
    max_images: int,
) -> PlacementInfo | None:
    if not text or not str(text).strip():
        return None
    raw = str(text).strip()
    seen_in_image: int | None = None
    match = _IMAGE_NUM_RE.search(raw)
    if match:
        seen_in_image = _clamp_image_index(int(match.group(1)), max_images)

    lower = raw.lower()
    horizontal: str | None = None
    for candidate in ("left", "right", "center"):
        if re.search(rf"\b{candidate}\b", lower):
            horizontal = candidate
            break

    vertical: str | None = None
    for candidate in ("top", "bottom"):
        if re.search(rf"\b{candidate}\b", lower):
            vertical = candidate
            break

    asset_location = _IMAGE_NUM_RE.sub("", raw).strip(" ,;-") or raw

    return placement_from_parts(
        asset_location=asset_location,
        horizontal=horizontal,
        vertical=vertical,
        seen_in_image=seen_in_image,
        in_frame_position=None,
        max_images=max_images,
        description=raw,
    )


def _location_hint_from_description(description: str | None) -> str | None:
    if not description:
        return None
    lower = description.lower()
    for needle, label in _PANEL_HINTS:
        if needle in lower:
            return label
    return None


def _labels_from_description(description: str | None) -> list[str]:
    if not description:
        return []
    found: list[str] = []
    for match in _QUOTED_RE.finditer(description):
        text = match.group(1).strip()
        if len(text) >= 2:
            found.append(text)
    for match in _BRANDING_RE.finditer(description):
        text = match.group(1).strip()
        if text:
            found.append(f"{text} branding")
    if "warning labels" in description.lower():
        found.append("warning labels")
    return found


def _has_sticker_placement_fields(item: LLMStickerItem) -> bool:
    return _sticker_richness(item) > 0


def _sticker_richness(item: LLMStickerItem) -> int:
    score = 0
    if item.asset_location:
        score += 2
    if item.horizontal:
        score += 1
    if item.seen_in_image is not None:
        score += 2
    if item.in_frame_position:
        score += 1
    return score


def _is_front_panel_label(label: str) -> bool:
    lower = label.lower()
    return (
        "front panel" in lower
        or "temperature display" in lower
        or "digital display" in lower
        or ("display" in lower and "front" in lower)
    )


def _is_side_panel_spec_label(label: str) -> bool:
    lower = label.lower()
    if _is_front_panel_label(label):
        return False
    return any(k in lower for k in _SIDE_SPEC_KEYWORDS)


def _is_side_panel_sticker(item: LLMStickerItem) -> bool:
    loc = (item.asset_location or "").lower()
    if "side" in loc and "panel" in loc:
        return True
    if loc in ("side panel",) or "side panel" in loc:
        return True
    return _is_side_panel_spec_label(item.label_text or "")


def _location_is_front(asset_location: str | None) -> bool:
    loc = (asset_location or "").lower()
    if not loc:
        return False
    if "side" in loc:
        return False
    return "front" in loc or loc == "front panel"


def _is_front_panel_sticker(item: LLMStickerItem) -> bool:
    if _location_is_front(item.asset_location):
        return True
    if _is_front_panel_label(item.label_text or ""):
        return True
    lower = (item.label_text or "").lower()
    if "branding" in lower and "breathe pure" in lower:
        return True
    if "quad air" in lower or "breathe pure" in lower:
        return True
    return False


def _front_image_from_description(description: str | None, max_images: int) -> int | None:
    if not description:
        return None
    for match in _FRONT_IMAGE_RE.finditer(description):
        raw = match.group(1) or match.group(2)
        if raw:
            clamped = _clamp_image_index(int(raw), max_images)
            if clamped is not None:
                return clamped
    return None


def _default_front_image(side_image: int | None, max_images: int) -> int | None:
    if max_images < 1:
        return None
    if max_images == 1:
        return 1
    for candidate in range(1, max_images + 1):
        if candidate != side_image:
            return candidate
    return 1


def _image_index_from_texts(*texts: str | None, max_images: int) -> int | None:
    for text in texts:
        if not text:
            continue
        match = _IMAGE_NUM_RE.search(str(text))
        if match:
            clamped = _clamp_image_index(int(match.group(1)), max_images)
            if clamped is not None:
                return clamped
    return None


def _mode_image_index(indices: list[int | None]) -> int | None:
    counts: dict[int, int] = {}
    for idx in indices:
        if isinstance(idx, int):
            counts[idx] = counts.get(idx, 0) + 1
    if not counts:
        return None
    return max(counts, key=counts.get)


def _canonical_side_panel_image(
    llm: LLMAnalysisResult,
    stickers: list[LLMStickerItem],
    max_images: int,
) -> int | None:
    seen = _clamp_image_index(llm.barcode_seen_in_image, max_images)
    if seen is not None:
        return seen
    parsed = _image_index_from_texts(
        llm.barcode_position,
        llm.tag_detection_reasoning,
        max_images=max_images,
    )
    if parsed is not None:
        return parsed
    side_indices = [
        _clamp_image_index(s.seen_in_image, max_images)
        for s in stickers
        if _is_side_panel_sticker(s)
    ]
    return _mode_image_index(side_indices)


def _canonical_front_panel_image(
    llm: LLMAnalysisResult,
    stickers: list[LLMStickerItem],
    max_images: int,
    side_image: int | None,
) -> int | None:
    front_indices = [
        _clamp_image_index(s.seen_in_image, max_images)
        for s in stickers
        if _is_front_panel_sticker(s)
    ]
    mode = _mode_image_index(front_indices)
    if mode is not None:
        return mode
    non_side = [
        _clamp_image_index(s.seen_in_image, max_images)
        for s in stickers
        if not _is_side_panel_sticker(s) and s.seen_in_image is not None
    ]
    mode = _mode_image_index(non_side)
    if mode is not None and mode != side_image:
        return mode
    from_desc = _front_image_from_description(llm.description, max_images)
    if from_desc is not None:
        return from_desc
    return _default_front_image(side_image, max_images)


def _harmonize_sticker_image_indices(
    stickers: list[LLMStickerItem],
    llm: LLMAnalysisResult,
    max_images: int,
) -> list[LLMStickerItem]:
    if not stickers:
        return stickers
    side_image = _canonical_side_panel_image(llm, stickers, max_images)
    front_image = _canonical_front_panel_image(llm, stickers, max_images, side_image)
    harmonized: list[LLMStickerItem] = []
    for s in stickers:
        target: int | None = None
        if _is_side_panel_sticker(s) and side_image is not None:
            target = side_image
        elif _is_front_panel_sticker(s) and front_image is not None:
            target = front_image
        clamped = _clamp_image_index(s.seen_in_image, max_images)
        if target is not None:
            harmonized.append(s.model_copy(update={"seen_in_image": target}))
        elif clamped is not None:
            harmonized.append(s.model_copy(update={"seen_in_image": clamped}))
        elif max_images == 1:
            harmonized.append(s.model_copy(update={"seen_in_image": 1}))
        else:
            harmonized.append(s.model_copy(update={"seen_in_image": clamped}))
    return harmonized


def _panel_key(item: LLMStickerItem) -> str | None:
    if _is_side_panel_sticker(item):
        return "side"
    if _is_front_panel_sticker(item):
        return "front"
    loc = (item.asset_location or "").strip().lower()
    return loc if loc else None


def stickers_image_index_need_review(
    stickers: list[LLMStickerItem] | None,
    max_images: int,
) -> bool:
    """True when stickers on the same panel family disagree on seen_in_image."""
    if not stickers:
        return False
    by_panel: dict[str, set[int | None]] = {}
    for s in stickers:
        key = _panel_key(s)
        if not key:
            continue
        idx = _clamp_image_index(s.seen_in_image, max_images)
        by_panel.setdefault(key, set()).add(idx)
    for indices in by_panel.values():
        non_null = {i for i in indices if i is not None}
        if len(non_null) > 1:
            return True
        if None in indices and len(non_null) >= 1 and len(indices) > 1:
            return True
    return False


def _infer_sticker_placement_fields(
    label: str,
    description: str | None,
    template: LLMStickerItem | None,
    barcode_seen_in_image: int | None,
    max_images: int,
) -> dict[str, str | int | None]:
    """Infer flat placement fields for stickers added from specs/features only."""
    lower = label.lower()
    desc = (description or "").lower()

    asset_location: str | None = None
    horizontal: str | None = None
    vertical: str | None = None
    in_frame: str | None = None
    seen_in_image: int | None = None

    for needle, loc in _PANEL_HINTS:
        if needle in lower:
            asset_location = loc
            break

    if "top right" in lower or "upper-right" in lower or "upper right" in lower:
        horizontal = "right"
        vertical = "top"
        in_frame = "top right"
    elif "top left" in lower:
        horizontal = "left"
        vertical = "top"
        in_frame = "top left"
    elif re.search(r"\bright\b", lower) and "left" not in lower:
        horizontal = "right"
    elif re.search(r"\bleft\b", lower):
        horizontal = "left"
    elif "center" in lower:
        horizontal = "center"

    if _is_front_panel_label(label):
        asset_location = asset_location or "front panel"
        horizontal = horizontal or "center"
        vertical = vertical or "center"
        if "top" in lower:
            vertical = "top"
            in_frame = in_frame or "upper-center"
    elif _is_side_panel_spec_label(label):
        asset_location = asset_location or "side panel"
        horizontal = horizontal or "right"
        vertical = vertical or "top"
        in_frame = in_frame or "top right"
        if "side panel" in desc:
            asset_location = "right side panel"
    elif "branding" in lower and "breathe pure" in lower:
        asset_location = asset_location or "front panel"
        horizontal = horizontal or "right"
        vertical = vertical or "top"
        in_frame = in_frame or "top right"
    elif "quad air" in lower or ("breathe pure" in lower and "protection" in lower):
        asset_location = asset_location or "front panel"
        horizontal = horizontal or "left"
        vertical = vertical or "top"
        in_frame = in_frame or "top left"

    if not asset_location and desc:
        if "side panel" in desc and _is_side_panel_spec_label(label):
            asset_location = "right side panel"
            horizontal = horizontal or "right"
        if "front panel" in desc and _is_front_panel_label(label):
            asset_location = "front panel"
            horizontal = horizontal or "center"

    if _is_side_panel_spec_label(label) and barcode_seen_in_image is not None:
        seen_in_image = barcode_seen_in_image

    is_front = _is_front_panel_label(label) or (
        "branding" in lower and "breathe pure" in lower
    ) or "quad air" in lower
    if seen_in_image is None and is_front and description:
        seen_in_image = _front_image_from_description(description, max_images)
        if seen_in_image is None and "front panel" in desc:
            seen_in_image = _image_index_from_texts(description, max_images=max_images)

    if template and _has_sticker_placement_fields(template):
        if not asset_location and template.asset_location:
            asset_location = template.asset_location
        if not horizontal and template.horizontal:
            horizontal = template.horizontal
        if not vertical and template.vertical:
            vertical = template.vertical
        if not in_frame and template.in_frame_position:
            in_frame = template.in_frame_position
        if (
            seen_in_image is None
            and template.seen_in_image is not None
            and _is_front_panel_label(label)
            and _is_front_panel_sticker(template)
        ):
            seen_in_image = template.seen_in_image

    seen_in_image = _clamp_image_index(seen_in_image, max_images)

    return {
        "asset_location": asset_location,
        "horizontal": horizontal,
        "vertical": vertical,
        "seen_in_image": seen_in_image,
        "in_frame_position": in_frame,
    }


def _backfill_sticker_placements(
    stickers: list[LLMStickerItem],
    llm: LLMAnalysisResult,
    max_images: int,
) -> list[LLMStickerItem]:
    if not stickers:
        return stickers

    template: LLMStickerItem | None = None
    best = -1
    for s in stickers:
        score = _sticker_richness(s)
        if score > best:
            best = score
            template = s

    barcode_seen = _clamp_image_index(llm.barcode_seen_in_image, max_images)
    filled: list[LLMStickerItem] = []
    for s in stickers:
        if _has_sticker_placement_fields(s):
            clamped_seen = _clamp_image_index(s.seen_in_image, max_images)
            if clamped_seen is None:
                if _is_side_panel_sticker(s) and barcode_seen is not None:
                    clamped_seen = barcode_seen
                elif max_images == 1:
                    clamped_seen = 1
            filled.append(s.model_copy(update={"seen_in_image": clamped_seen}))
            continue
        fields = _infer_sticker_placement_fields(
            s.label_text or "",
            llm.description,
            template,
            barcode_seen,
            max_images,
        )
        if any(fields.values()):
            filled.append(s.model_copy(update=fields))
        else:
            filled.append(s)
    return _harmonize_sticker_image_indices(filled, llm, max_images)


def merge_sticker_sources(
    llm: LLMAnalysisResult,
    images_analyzed: int = 10,
) -> LLMAnalysisResult:
    """Union stickers from all same-response sources (exhaustive, deduped)."""
    by_label: dict[str, LLMStickerItem] = {}

    def _add(label: str, default_type: str, item: LLMStickerItem | None = None) -> None:
        text = label.strip()
        if not text:
            return
        key = text.lower()
        if len(by_label) >= _MAX_STICKERS and key not in by_label:
            return
        if item is not None and item.label_text:
            existing = by_label.get(key)
            if existing is None or _sticker_richness(item) > _sticker_richness(existing):
                by_label[key] = item
            return
        if key not in by_label:
            by_label[key] = LLMStickerItem(
                label_text=text,
                sticker_type=_norm_enum(default_type, _STICKER_TYPES) or default_type,
            )

    for raw in llm.stickers or []:
        if raw.label_text:
            st = _norm_enum(raw.sticker_type, _STICKER_TYPES) or "other"
            _add(raw.label_text, st, raw)

    for label in _clean_list(llm.visible_labels, limit=_MAX_STICKERS):
        _add(label, "other")

    for spec in _clean_list(llm.specifications, limit=_MAX_STICKERS):
        _add(spec, "spec")

    for feat in _clean_list(llm.distinguishing_features, limit=_MAX_STICKERS):
        _add(feat, "brand")

    for label in _labels_from_description(llm.description):
        _add(label, "other")

    stickers = _backfill_sticker_placements(
        list(by_label.values())[:_MAX_STICKERS],
        llm,
        images_analyzed,
    )
    visible_labels = [s.label_text for s in stickers if s.label_text]
    return llm.model_copy(update={"stickers": stickers, "visible_labels": visible_labels})


def enrich_llm_sticker_labels(
    llm: LLMAnalysisResult,
    images_analyzed: int = 10,
) -> LLMAnalysisResult:
    """Backward-compatible alias for merge_sticker_sources."""
    return merge_sticker_sources(llm, images_analyzed=images_analyzed)


def _barcode_placement_from_llm(
    llm: LLMAnalysisResult,
    max_images: int,
) -> PlacementInfo | None:
    barcode_phrase = (llm.barcode_position or "").strip() or None
    flat = placement_from_parts(
        asset_location=llm.barcode_asset_location,
        horizontal=llm.barcode_horizontal,
        vertical=llm.barcode_vertical,
        seen_in_image=llm.barcode_seen_in_image,
        in_frame_position=llm.barcode_in_frame_position,
        max_images=max_images,
        description=barcode_phrase,
    )
    if flat is not None:
        if flat.description is None:
            flat = flat.model_copy(update={"description": format_tag_position(flat)})
        return flat

    parsed = parse_barcode_position_text(llm.barcode_position, max_images)
    if parsed is not None:
        return parsed

    hint = _location_hint_from_description(llm.description)
    if hint:
        return placement_from_parts(
            asset_location=hint,
            horizontal=None,
            vertical=None,
            seen_in_image=None,
            in_frame_position=None,
            max_images=max_images,
        )
    return None


def format_tag_position(placement: PlacementInfo | None) -> str | None:
    if placement is None:
        return None
    parts: list[str] = []
    if placement.asset_location:
        parts.append(placement.asset_location)
    if placement.horizontal:
        parts.append(placement.horizontal)
    if placement.vertical and placement.vertical != "center":
        parts.append(placement.vertical)
    if placement.in_frame_position:
        parts.append(f"in frame {placement.in_frame_position}")
    if placement.seen_in_image is not None:
        parts.append(f"Image {placement.seen_in_image}")
    return ", ".join(parts) if parts else None


def llm_has_barcode_placement(llm: LLMAnalysisResult, images_analyzed: int) -> bool:
    if (llm.barcode_position or "").strip():
        return True
    return _barcode_placement_from_llm(llm, images_analyzed) is not None


def identifiers_need_review(
    llm: LLMAnalysisResult,
    normalized_tag: str | None,
    images_analyzed: int,
) -> bool:
    if not normalized_tag:
        return False
    return not llm_has_barcode_placement(llm, images_analyzed)


def _to_sticker(item: LLMStickerItem, max_images: int) -> StickerItem | None:
    label = (item.label_text or "").strip()
    if not label:
        return None
    sticker_type = _norm_enum(item.sticker_type, _STICKER_TYPES) or "other"
    placement = placement_from_parts(
        asset_location=item.asset_location,
        horizontal=item.horizontal,
        vertical=item.vertical,
        seen_in_image=item.seen_in_image,
        in_frame_position=item.in_frame_position,
        max_images=max_images,
    )
    return StickerItem(
        label_text=label,
        sticker_type=sticker_type,
        placement=placement,
    )


_INVALID_TAG_RAW = frozenset(
    {"UNREADABLE", "NONE", "N/A", "NOT VISIBLE", "NOT FOUND", "NO TAG", "NOT DETECTED"}
)


def _raw_tag_upper(llm: LLMAnalysisResult) -> str:
    return (llm.asset_tag_number or "").strip().upper()


def _has_tag_number_evidence(normalized_tag: str | None, llm: LLMAnalysisResult) -> bool:
    if normalized_tag:
        return True
    raw = _raw_tag_upper(llm)
    return bool(raw) and raw not in _INVALID_TAG_RAW


def build_identifiers(
    llm: LLMAnalysisResult,
    normalized_tag: str | None,
    images_analyzed: int,
) -> Identifiers:
    raw_tag_upper = _raw_tag_upper(llm)
    # Readable only when we have a validated digit tag — never trust tag_readable alone.
    tag_readable = bool(normalized_tag)
    placement = _barcode_placement_from_llm(llm, images_analyzed)
    if raw_tag_upper == "UNREADABLE":
        barcode_present = bool(llm.barcode_present)
    elif _has_tag_number_evidence(normalized_tag, llm):
        barcode_present = True
    else:
        barcode_present = False

    if llm.barcode_position:
        tag_position = str(llm.barcode_position).strip() or None
    else:
        tag_position = format_tag_position(placement)

    stickers: list[StickerItem] = []
    seen_keys: set[tuple[str, int | None]] = set()
    for raw in llm.stickers or []:
        sticker = _to_sticker(raw, images_analyzed)
        if sticker is None:
            continue
        img = sticker.placement.seen_in_image if sticker.placement else None
        key = (sticker.label_text.lower(), img)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        stickers.append(sticker)
        if len(stickers) >= _MAX_STICKERS:
            break

    visible_labels = [s.label_text for s in stickers]
    if not visible_labels:
        visible_labels = _clean_list(llm.visible_labels)

    reasoning = (llm.tag_detection_reasoning or "").strip() or None

    barcode = BarcodeDetails(
        present=barcode_present,
        readable=tag_readable,
        placement=placement,
        detection_reasoning=reasoning,
    )

    return Identifiers(
        asset_tag_number=normalized_tag,
        asset_tag_number_raw=llm.asset_tag_number,
        tag_readable=tag_readable,
        tag_position=tag_position,
        tag_detection_reasoning=reasoning,
        visible_labels=visible_labels,
        barcode=barcode,
        stickers=stickers,
    )
