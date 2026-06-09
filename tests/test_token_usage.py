"""Tests for image/text token breakdown and reconciliation."""

from types import SimpleNamespace

from app.services.gemini import (
    MEDIA_RESOLUTION_IMAGE_TOKENS,
    _extract_usage,
    _per_image_token_budget,
)


def _fake_response(prompt, candidates, total, image_modality_tokens=None):
    details = []
    if image_modality_tokens is not None:
        text_part = max(prompt - image_modality_tokens, 0)
        details = [
            SimpleNamespace(modality="IMAGE", token_count=image_modality_tokens),
            SimpleNamespace(modality="TEXT", token_count=text_part),
        ]
    um = SimpleNamespace(
        prompt_token_count=prompt,
        candidates_token_count=candidates,
        total_token_count=total,
        prompt_tokens_details=details,
    )
    return SimpleNamespace(usage_metadata=um)


def test_per_image_budget_matches_official_table():
    assert _per_image_token_budget("high") == 1120
    assert _per_image_token_budget("low") == 280
    assert _per_image_token_budget("medium") == 560
    assert _per_image_token_budget("ultra_high") == 2240
    assert MEDIA_RESOLUTION_IMAGE_TOKENS["unspecified"] == 1120


def test_actual_breakdown_reconciles_with_input():
    # 3 images at high; API reports 3360 image tokens out of 4400 input.
    resp = _fake_response(prompt=4400, candidates=900, total=5300, image_modality_tokens=3360)
    usage = _extract_usage(resp, images_sent=3, media_resolution="high")

    assert usage.input_tokens == 4400
    assert usage.image_tokens == 3360
    assert usage.text_tokens == 1040
    assert usage.image_tokens + usage.text_tokens == usage.input_tokens
    assert usage.images_sent_to_gemini == 3
    assert usage.per_image_token_budget == 1120
    assert usage.estimated_image_tokens == 3 * 1120


def test_estimate_fallback_when_no_modality_details():
    # No prompt_tokens_details -> use official estimate, capped to input, still reconciles.
    resp = _fake_response(prompt=2200, candidates=500, total=2700, image_modality_tokens=None)
    usage = _extract_usage(resp, images_sent=1, media_resolution="high")

    assert usage.estimated_image_tokens == 1120
    assert usage.image_tokens == 1120  # within input (2200)
    assert usage.text_tokens == 2200 - 1120
    assert usage.image_tokens + usage.text_tokens == usage.input_tokens


def test_image_tokens_capped_to_input():
    # Estimate exceeds input (small/edge case) -> capped so it never goes negative.
    resp = _fake_response(prompt=900, candidates=100, total=1000, image_modality_tokens=None)
    usage = _extract_usage(resp, images_sent=5, media_resolution="high")

    assert usage.estimated_image_tokens == 5 * 1120
    assert usage.image_tokens == 900
    assert usage.text_tokens == 0
    assert usage.image_tokens + usage.text_tokens == usage.input_tokens
