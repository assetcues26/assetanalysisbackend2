"""Tests for Tagging AI pass/fail computation."""

from app.services.tagging_ai_client import compute_ai_status


def _full_pass_response():
    return {
        "imageReadability": "Y",
        "namedescriptionmatch": "Y",
        "subcatmodelmatch": "Y",
        "detectedtagnumbermatch": "Y",
        "costvalidation": {"costmatch": "Y"},
        "acquisitiondatevalidation": {"datematch": "Y"},
    }


def test_compute_ai_status_pass():
    status, summary = compute_ai_status(_full_pass_response())
    assert status == "pass"
    assert all(summary["checks"].values())


def test_compute_ai_status_fail_on_subcat():
    data = _full_pass_response()
    data["subcatmodelmatch"] = "N"
    status, summary = compute_ai_status(data)
    assert status == "fail"
    assert summary["checks"]["subcatmodelmatch"] is False


def test_compute_ai_status_fail_on_tag():
    data = _full_pass_response()
    data["detectedtagnumbermatch"] = "N"
    status, _ = compute_ai_status(data)
    assert status == "fail"


def test_compute_ai_status_fail_on_cost():
    data = _full_pass_response()
    data["costvalidation"] = {"costmatch": "N"}
    status, _ = compute_ai_status(data)
    assert status == "fail"


def test_compute_ai_status_field_comparison():
    metadata = {
        "assetname": "Dell Laptop",
        "tagnumber": "TAG-1",
        "cost": "125000",
        "acquisitiondate": "15-08-2023",
        "subcategoryname": "Laptops",
        "makemodelname": "Latitude 5420",
    }
    data = _full_pass_response()
    data["subcatmodelmatch"] = "N"
    data["detectedAsset"] = "HP Laptop"
    data["detectedtagnumber"] = "TAG-2"
    status, summary = compute_ai_status(data, metadata)
    assert status == "fail"
    assert "field_comparison" in summary
    assert summary["field_comparison"]["namedescriptionmatch"]["registered"] == "Dell Laptop"
    assert summary["field_comparison"]["namedescriptionmatch"]["detected"] == "HP Laptop"
