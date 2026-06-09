# API output fields (collage vs multi)

Both `POST /v1/assets/analyze/collage` and `POST /v1/assets/analyze/multi` return the same `AnalyzeResponse` JSON shape defined in [`app/models/responses.py`](../app/models/responses.py).

## One Gemini call (prompt v2)

Each analyze request uses a **single** `generate_content` call with internal reasoning fields (`reasoning.*`) and `valuation_inputs` only. Final FMV, NBV proxy, and repair plan are computed in Python (`valuation_engine`, `nbv_engine`, `repair_policy`).

## `reasoning_summary`

Client-safe summary: `identity_candidates[]`, `selected_identity_rationale`, `uncertainty_flags[]`, `narrative`.

## `valuation`

- `status`: `ok` | `withheld` | `indicative_only`
- `as_is` — current market value (like-new × age × **damage/condition**)
- `like_new_reference` — computed server-side
- `nbv` — age/depreciation proxy only (**no damage adjustment**)
- `nbv_exceeds_as_is` — `true` | `false` | `null` (midpoint compare: NBV vs as-is)
- `nbv_vs_as_is_note` — human-readable impairment hint when NBV exceeds as-is

Default model: `gemini-3.1-flash-lite` (thinking disabled; reasoning via prompt v2 schema).

## `condition.repair_plan`

Structured per-damage repair decisions with `overall_repair_needed` and `items[]`.

## `identifiers`

- Legacy: `asset_tag_number`, `tag_position`, `tag_detection_reasoning`, `visible_labels[]`
- `barcode`: `{ present, readable, placement, detection_reasoning }`
- `stickers[]`: one object per distinct physical label — `{ label_text, sticker_type, placement }`
- `placement`: `{ asset_location, horizontal, vertical, seen_in_image, in_frame_position, description }`. `description` is a detailed natural-language phrase (panel, sub-region, surface, adjacent landmarks, distance from edge, bar orientation, Image N). Populated for the barcode; `identifiers.tag_position` mirrors the same phrase.

## `condition.damage_items[]`

Each defect (additive `placement`):

- `location`, `type`, `severity`, `seen_in_image`, `detail`, `affects_function`, `repair_action`
- `placement`: `{ asset_location, horizontal, vertical, seen_in_image, in_frame_position }`

## `review_required`

Set when confidence is low, tag unreadable, barcode placement missing, label hints without stickers after merge, or damage mentioned in narrative without `damage_items[]`.
