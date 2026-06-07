"""Tests for FAR SLM depreciation on demo catalog."""

from datetime import date

import pytest

from app.services.catalog_far import (
    FAR_AS_OF_DATE,
    compute_slm_far,
    enrich_catalog,
    enrich_catalog_item,
    resolve_useful_life_years,
)
from app.services.demo_catalog import load_demo_catalog


def test_macbook_nbv_matches_erp_register():
    """CIPLA register shows NBV 3,104 on cost 62,080 — SLM to salvage after full life."""
    far = compute_slm_far(62080, date(2021, 1, 14), 3.0, as_of=FAR_AS_OF_DATE)
    assert far["book_nbv_inr"] == 3104
    assert far["residual_value_inr"] == 3104
    assert far["accumulated_depreciation_inr"] == 58976


def test_laptop_fully_depreciated_after_useful_life():
    far = compute_slm_far(72000, date(2021, 3, 10), 3.0, as_of=FAR_AS_OF_DATE)
    assert far["book_nbv_inr"] == 3600
    assert far["asset_age_years"] > 3


def test_enrich_catalog_item_computes_nbv():
    item = enrich_catalog_item(
        {
            "catalog_id": "ac-001",
            "subcategory": "Split AC",
            "acquisition_date": "2021-06-15",
            "original_cost_inr": 28500,
            "useful_life_years": 15,
        }
    )
    assert item["book_nbv_inr"] == 19516
    assert item["accumulated_depreciation_inr"] == 8984
    assert item["depreciation_method"] == "SLM"


def test_load_demo_catalog_enriched():
    load_demo_catalog.cache_clear()
    catalog = load_demo_catalog()
    assert len(catalog) == 9
    macbook = next(a for a in catalog if a["catalog_id"] == "macbook-004")
    assert macbook["book_nbv_inr"] == 3104
    assert macbook["asset_number"] == "1000002129"
    for row in catalog:
        assert row["book_nbv_inr"] <= row["original_cost_inr"]
        assert row["accumulated_depreciation_inr"] >= 0
        assert row["far_as_of_date"] == FAR_AS_OF_DATE.isoformat()


def test_resolve_useful_life_defaults():
    assert resolve_useful_life_years({"subcategory": "Laptop"}) == 3.0
    assert resolve_useful_life_years({"category": "HVAC", "subcategory": "Split AC"}) == 15.0


def test_invalid_cost_raises():
    with pytest.raises(ValueError):
        compute_slm_far(0, date(2020, 1, 1), 5)
