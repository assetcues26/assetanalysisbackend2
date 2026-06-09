"""Audit session endpoint — adapts the AI Audit frontend to the analysis API."""

from __future__ import annotations

import base64
import json
from io import BytesIO

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.config import Settings, get_settings
from app.models.responses import AnalyzeResponse, UnifiedViewMethod
from app.services.analyzer import AssetAnalysisService
from app.services.gemini import GeminiService
from app.services.rate_limiter import RateLimiter
from app.utils.uploads import resolve_uploaded_images

router = APIRouter()

_rate_limiter: RateLimiter | None = None
_analyzer: AssetAnalysisService | None = None


def get_rate_limiter(settings: Settings = Depends(get_settings)) -> RateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter(settings.rate_limit_per_minute)
    return _rate_limiter


def get_analyzer(settings: Settings = Depends(get_settings)) -> AssetAnalysisService:
    global _analyzer
    if _analyzer is None:
        _analyzer = AssetAnalysisService(settings=settings, gemini=GeminiService(settings))
    return _analyzer


def _data_url(raw: bytes, mime: str = "image/jpeg") -> str:
    encoded = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _to_frontend_result(
    analysis: AnalyzeResponse,
    asset_raw: bytes | None,
    barcode_raw: bytes | None,
    barcode_skipped: bool,
) -> dict:
    barcode = analysis.identifiers.barcode
    tag_value = analysis.identifiers.asset_tag_number or ""
    barcode_readable = bool(barcode.readable) if barcode.present else False

    placement = ""
    if barcode.placement:
        placement = (
            barcode.placement.description
            or barcode.placement.asset_location
            or ""
        )

    match_successful = barcode_skipped or barcode_readable or bool(tag_value)
    confidence = analysis.confidence.overall or analysis.valuation.confidence

    return {
        "asset_image": _data_url(asset_raw) if asset_raw else None,
        "barcode_image": _data_url(barcode_raw) if barcode_raw else None,
        "yolo_bbox": None,
        "vlm_result": {
            "asset_details": {
                "name": analysis.asset.name or "Unknown asset",
                "description": analysis.asset.description or analysis.condition.summary or "",
                "condition": analysis.condition.summary or "Not assessed",
                "condition_rating": analysis.condition.grade or "N/A",
            },
            "barcode_details": {
                "value": tag_value,
                "position": placement or "Not detected",
                "condition": barcode.detection_reasoning or ("Skipped" if barcode_skipped else "Not detected"),
                "condition_rating": "Readable" if barcode_readable else ("Skipped" if barcode_skipped else "Unreadable"),
            },
            "mapping_confidence": confidence,
            "match_successful": match_successful,
            "is_swapped": False,
            "verification_reason": (
                barcode.detection_reasoning
                or analysis.identifiers.tag_detection_reasoning
                or analysis.condition.summary
                or "Analysis completed from uploaded images."
            ),
        },
    }


async def _read_upload(upload: UploadFile) -> bytes:
    data = await upload.read()
    await upload.seek(0)
    return data


@router.post("/audit/session", tags=["Audit"])
async def audit_session(
    session_metadata: str = Form(...),
    images: list[UploadFile] = File(...),
    settings: Settings = Depends(get_settings),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
    analyzer: AssetAnalysisService = Depends(get_analyzer),
) -> list[dict]:
    rate_limiter.check("audit")

    try:
        meta = json.loads(session_metadata)
        pairs_meta = meta.get("pairs_metadata", [])
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid session_metadata JSON",
        ) from exc

    if not pairs_meta:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No asset pairs in session",
        )

    by_name: dict[str, UploadFile] = {}
    for img in images:
        if img.filename:
            by_name[img.filename] = img

    results: list[dict] = []

    for index, pair in enumerate(pairs_meta):
        asset_upload = by_name.get(f"asset_{index}.jpg")
        if not asset_upload:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Missing asset image for pair {index}",
            )

        barcode_skipped = bool(pair.get("barcode_skipped"))
        barcode_upload = None if barcode_skipped else by_name.get(f"barcode_{index}.jpg")

        asset_raw = await _read_upload(asset_upload)
        barcode_raw = await _read_upload(barcode_upload) if barcode_upload else None

        uploads: list[UploadFile] = [
            UploadFile(file=BytesIO(asset_raw), filename=f"asset_{index}.jpg"),
        ]
        if barcode_raw:
            uploads.append(
                UploadFile(file=BytesIO(barcode_raw), filename=f"barcode_{index}.jpg"),
            )

        files = await resolve_uploaded_images(uploads, settings)

        try:
            analysis = await analyzer.analyze(
                files=files,
                method=UnifiedViewMethod.MULTI_IMAGE,
                locale="en",
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
                headers={"Retry-After": "30"},
            ) from exc

        results.append(
            _to_frontend_result(
                analysis,
                asset_raw,
                barcode_raw,
                barcode_skipped,
            )
        )

    return results
