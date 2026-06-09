"""Tests for condition grade normalization and fallbacks."""

from app.services.condition_mapper import resolve_condition_grade


def test_resolve_condition_grade_aliases():
    assert resolve_condition_grade("good") == "Good"
    assert resolve_condition_grade("FAIR") == "Fair"
    assert resolve_condition_grade("damaged") == "Poor"


def test_resolve_condition_grade_from_score():
    assert resolve_condition_grade(None, 8) == "Good"
    assert resolve_condition_grade(None, 75) == "Good"
    assert resolve_condition_grade(None, 55) == "Fair"
    assert resolve_condition_grade(None, 30) == "Poor"


def test_resolve_condition_grade_prefers_explicit_grade():
    assert resolve_condition_grade("Fair", 90) == "Fair"
