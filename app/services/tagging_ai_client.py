"""Tagging AI client and pass/fail computation."""

from __future__ import annotations

import time
from typing import Any

import httpx
import structlog

from app.config import Settings
from app.utils.uploads import sniff_image_mime

logger = structlog.get_logger()


def _resolve_image_mime(data: bytes, fallback: str) -> str:
    return sniff_image_mime(data) or fallback


def _filename_for_mime(mime: str, stem: str) -> str:
    ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}.get(mime, ".jpg")
    return f"{stem}{ext}"

TEXT_FIELDS = (
    "assetid",
    "assetname",
    "description",
    "tagnumber",
    "assetnumber",
    "assetclassid",
    "assetclassname",
    "categoryid",
    "categoryname",
    "subcategoryid",
    "subcategoryname",
    "makemodelid",
    "makemodelname",
    "companyid",
    "company",
    "customerid",
    "assettaggingdetailid",
    "cost",
    "acquisitiondate",
)


def build_field_comparison(
    metadata: dict[str, Any], response: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """Side-by-side registered vs detected values per validation check."""
    cost_val = response.get("costvalidation") or {}
    date_val = response.get("acquisitiondatevalidation") or {}
    return {
        "imageReadability": {
            "field": "image",
            "registered": "uploaded",
            "detected": response.get("condition") or response.get("detectedAsset"),
            "match": response.get("imageReadability") == "Y",
        },
        "namedescriptionmatch": {
            "field": "assetname",
            "registered": metadata.get("assetname"),
            "detected": response.get("detectedAsset"),
            "match": response.get("namedescriptionmatch") == "Y",
        },
        "subcatmodelmatch": {
            "field": "makemodelname",
            "registered": f"{metadata.get('subcategoryname') or ''} / {metadata.get('makemodelname') or ''}".strip(
                " /"
            ),
            "detected": f"{response.get('recommendedsubcategory') or ''} / {response.get('recommendedmakemodel') or ''}".strip(
                " /"
            ),
            "match": response.get("subcatmodelmatch") == "Y",
        },
        "detectedtagnumbermatch": {
            "field": "tagnumber",
            "registered": metadata.get("tagnumber"),
            "detected": response.get("detectedtagnumber"),
            "match": response.get("detectedtagnumbermatch") == "Y",
        },
        "costmatch": {
            "field": "cost",
            "registered": metadata.get("cost"),
            "detected": cost_val.get("detectedcost") or cost_val.get("expectedcost"),
            "match": cost_val.get("costmatch") == "Y",
        },
        "datematch": {
            "field": "acquisitiondate",
            "registered": metadata.get("acquisitiondate"),
            "detected": date_val.get("detecteddate") or date_val.get("expecteddate"),
            "match": date_val.get("datematch") == "Y",
        },
    }


def compute_ai_status(
    response: dict[str, Any], metadata: dict[str, Any] | None = None
) -> tuple[str, dict[str, Any]]:
    """Return (pass|fail, failure_summary) from Tagging AI response."""
    checks = {
        "imageReadability": response.get("imageReadability") == "Y",
        "namedescriptionmatch": response.get("namedescriptionmatch") == "Y",
        "subcatmodelmatch": response.get("subcatmodelmatch") == "Y",
        "detectedtagnumbermatch": response.get("detectedtagnumbermatch") == "Y",
        "costmatch": (response.get("costvalidation") or {}).get("costmatch") == "Y",
        "datematch": (response.get("acquisitiondatevalidation") or {}).get("datematch") == "Y",
    }
    status = "pass" if all(checks.values()) else "fail"
    cost_val = response.get("costvalidation") or {}
    date_val = response.get("acquisitiondatevalidation") or {}
    failure_summary: dict[str, Any] = {
        "checks": checks,
        "reasoning": response.get("reasoning"),
        "recommendedsubcategory": response.get("recommendedsubcategory"),
        "recommendedmakemodel": response.get("recommendedmakemodel"),
        "detectedtagnumber": response.get("detectedtagnumber"),
        "tagnumber": response.get("tagnumber") or metadata.get("tagnumber") if metadata else response.get("tagnumber"),
        "costvalidation": cost_val,
        "acquisitiondatevalidation": date_val,
        "imageReadability": response.get("imageReadability"),
        "namedescriptionmatchpercent": response.get("namedescriptionmatchpercent"),
        "subcatmodelmatchpercent": response.get("subcatmodelmatchpercent"),
        "detectedtagnumbermatchpercent": response.get("detectedtagnumbermatchpercent"),
        "costmatchpercent": cost_val.get("costmatchpercent") or cost_val.get("confidence"),
        "datematchpercent": date_val.get("datematchpercent") or date_val.get("confidence"),
    }
    if metadata:
        failure_summary["field_comparison"] = build_field_comparison(metadata, response)
    return status, failure_summary


def extract_summary_fields(response: dict[str, Any]) -> dict[str, str | None]:
    return {
        "detected_asset": response.get("detectedAsset"),
        "condition": response.get("condition"),
        "namedescriptionmatch": response.get("namedescriptionmatch"),
        "subcatmodelmatch": response.get("subcatmodelmatch"),
        "detectedtagnumbermatch": response.get("detectedtagnumbermatch"),
        "costmatch": (response.get("costvalidation") or {}).get("costmatch"),
        "datematch": (response.get("acquisitiondatevalidation") or {}).get("datematch"),
    }


async def analyze_asset_with_tagging_ai(
    settings: Settings,
    metadata: dict[str, Any],
    asset_image: bytes | None,
    barcode_image: bytes | None = None,
    *,
    asset_mime: str = "image/jpeg",
    barcode_mime: str = "image/jpeg",
) -> tuple[dict[str, Any], str | None, float]:
    """
    POST multipart to Tagging AI.
    Returns (response_json, request_id, elapsed_seconds).
    """
    url = settings.tagging_ai_api_url.strip()
    if not url:
        raise ValueError("TAGGING_AI_API_URL is not configured")

    if not asset_image and not barcode_image:
        raise ValueError(
            "At least one image (assetimage or barcodeimage) is required for Tagging AI"
        )

    data: dict[str, str] = {}
    for key in TEXT_FIELDS:
        value = metadata.get(key)
        if value is not None and value != "":
            data[key] = str(value)

    files: list[tuple[str, tuple[str, bytes, str]]] = []
    if asset_image:
        resolved_asset_mime = _resolve_image_mime(asset_image, asset_mime)
        files.append(
            (
                "assetimage",
                (
                    _filename_for_mime(resolved_asset_mime, "asset"),
                    asset_image,
                    resolved_asset_mime,
                ),
            )
        )
    if barcode_image:
        resolved_barcode_mime = _resolve_image_mime(barcode_image, barcode_mime)
        files.append(
            (
                "barcodeimage",
                (
                    _filename_for_mime(resolved_barcode_mime, "barcode"),
                    barcode_image,
                    resolved_barcode_mime,
                ),
            )
        )

    started = time.perf_counter()
    timeout = httpx.Timeout(settings.tagging_ai_timeout_seconds, connect=10.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, data=data, files=files)

    elapsed = time.perf_counter() - started
    request_id = response.headers.get("X-Request-ID")

    body = response.json()
    if not response.is_success:
        message = body.get("error", {}).get("message") if isinstance(body, dict) else str(body)
        raise RuntimeError(message or f"Tagging AI HTTP {response.status_code}")

    if not isinstance(body, dict):
        raise RuntimeError("Tagging AI returned non-JSON response")

    return body, request_id, elapsed
