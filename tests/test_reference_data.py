"""Reference pricing tables load from JSON, not code constants."""

from app.services.reference_data import load_reference_data, valuation_rules


def test_valuation_rules_loaded_from_json():
    data = load_reference_data()
    rules = valuation_rules(data)
    assert rules["as_is_band_pct"] == 0.08
    assert rules["severity_multipliers"]["severe"] == 0.80
    assert "consumer_electronics" in data["category_segment_keywords"]
