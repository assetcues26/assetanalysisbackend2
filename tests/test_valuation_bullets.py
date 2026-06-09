"""Tests for valuation bullet formatting."""

from app.utils.valuation_bullets import dedupe_bullets, normalize_bullet, split_prose_to_bullets


def test_normalize_bullet_adds_period():
    assert normalize_bullet("Hello world") == "Hello world."


def test_split_prose_to_bullets():
    text = (
        "First sentence here. Second sentence follows. "
        "In the Indian market, a 1.5-ton split AC would retain value."
    )
    bullets = split_prose_to_bullets(text)
    assert len(bullets) >= 2
    assert all(b.endswith((".", "!", "?")) for b in bullets)


def test_dedupe_substring_bullets():
    bullets = dedupe_bullets(
        [
            "Site context: Kashmir — moderate urban climate.",
            "Site context: Kashmir — moderate urban climate. Extra detail.",
        ]
    )
    assert len(bullets) == 1
