"""V6 demo endpoints — catalog + ERP-aware multi-image analysis."""

from __future__ import annotations

import json
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.models.demo_context import DemoContext
from app.models.responses import AnalyzeResponse
from app.services.demo_analyzer import DemoAnalysisService
from app.services.demo_catalog import load_demo_catalog
from app.services.gemini_v6_demo import GeminiV6DemoService
from app.services.metrics import REQUEST_COUNT, REQUEST_LATENCY
from app.services.rate_limiter import RateLimiter
from app.utils.timing import timer
from app.utils.uploads import MULTI_FILE_OPENAPI, resolve_uploaded_images

router = APIRouter()
logger = structlog.get_logger()

_rate_limiter: RateLimiter | None = None
_analyzer: DemoAnalysisService | None = None


def get_rate_limiter(settings: Settings = Depends(get_settings)) -> RateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter(settings.rate_limit_per_minute)
    return _rate_limiter


def get_demo_analyzer(settings: Settings = Depends(get_settings)) -> DemoAnalysisService:
    global _analyzer
    if _analyzer is None:
        _analyzer = DemoAnalysisService(
            settings=settings, gemini=GeminiV6DemoService(settings)
        )
    return _analyzer


@router.get("/demo/catalog", tags=["V6 Demo"])
async def get_demo_catalog() -> list[dict]:
    return load_demo_catalog()


@router.post(
    "/demo/analyze/multi",
    response_model=AnalyzeResponse,
    tags=["V6 Demo"],
    summary="V6 demo: analyze images with ERP context",
    openapi_extra=MULTI_FILE_OPENAPI,
)
async def analyze_demo_multi(
    images: Annotated[list[UploadFile], File(description="1-10 asset photos")],
    demo_context: Annotated[str, Form(description="JSON DemoContext payload")],
    locale: Annotated[str, Form(description="Output language")] = "en-IN",
    settings: Settings = Depends(get_settings),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
    analyzer: DemoAnalysisService = Depends(get_demo_analyzer),
) -> AnalyzeResponse:
    rate_limiter.check("v6-demo")
    try:
        ctx = DemoContext.model_validate(json.loads(demo_context))
    except (json.JSONDecodeError, ValidationError) as exc:
        REQUEST_COUNT.labels(status="400").inc()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid demo_context: {exc}",
        ) from exc

    real_count = len(
        [img for img in (images or []) if img is not None and (img.filename or img.content_type)]
    )
    if real_count > settings.max_images:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"At most {settings.max_images} images allowed "
                f"(got {real_count})."
            ),
        )

    files = await resolve_uploaded_images(images, settings)

    with timer() as elapsed:
        try:
            result = await analyzer.analyze(
                files=files, demo_context=ctx, locale=locale
            )
        except ValueError as exc:
            REQUEST_COUNT.labels(status="400").inc()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc
        except RuntimeError as exc:
            REQUEST_COUNT.labels(status="503").inc()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
                headers={"Retry-After": "30"},
            ) from exc

    REQUEST_COUNT.labels(status="200").inc()
    REQUEST_LATENCY.observe(elapsed[0] / 1000)
    return result
