"""Asset analysis API — two autopilot endpoints (collage + multi-image)."""

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.config import Settings, get_settings
from app.markets.registry import resolve_market
from app.models.responses import AnalyzeResponse, HealthResponse, UnifiedViewMethod
from app.services.analyzer import AssetAnalysisService
from app.services.gemini import GeminiService
from app.services.metrics import ANALYSIS_METHOD, REQUEST_COUNT, REQUEST_LATENCY
from app.services.rate_limiter import RateLimiter
from app.utils.timing import timer
from app.utils.uploads import MULTI_FILE_OPENAPI, resolve_uploaded_images

router = APIRouter()
logger = structlog.get_logger()

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


@router.get("/health", response_model=HealthResponse, tags=["Health"])
async def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    gemini = GeminiService(settings)
    return HealthResponse(status="ok", gemini_configured=gemini.is_configured())


async def _run_analysis(
    images: list[UploadFile],
    method: UnifiedViewMethod,
    locale: str,
    market_region: str,
    settings: Settings,
    rate_limiter: RateLimiter,
    analyzer: AssetAnalysisService,
    processing_mode: str | None = None,
    api_route: str | None = None,
) -> AnalyzeResponse:
    rate_limiter.check("poc")
    real_count = len([img for img in (images or []) if img is not None and (img.filename or img.content_type)])
    limit = settings.upload_image_limit
    if real_count > limit:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"At most {limit} images allowed "
                f"(got {real_count}). Use fewer angles or split into multiple requests."
            ),
        )
    files = await resolve_uploaded_images(images, settings)

    with timer() as elapsed:
        try:
            result = await analyzer.analyze(
                files=files,
                method=method,
                locale=locale,
                market_region=market_region,
                processing_mode=processing_mode,
                api_route=api_route,
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
    ANALYSIS_METHOD.labels(method=method.value).inc()
    return result


@router.post(
    "/assets/analyze/collage",
    response_model=AnalyzeResponse,
    tags=["Analysis"],
    summary="Analyze asset by merging images into one collage (autopilot)",
    description=(
        "Upload 1-10 photos of the same asset. The endpoint merges them into a single "
        "labeled collage, sends ONE image to Gemini, and returns damage analysis, "
        "valuation, token usage, and cost. No separate conversion step."
    ),
    openapi_extra=MULTI_FILE_OPENAPI,
)
async def analyze_collage(
    images: Annotated[list[UploadFile], File(description="1-10 asset photos")],
    locale: Annotated[str | None, Form(description="Output language")] = None,
    market_region: Annotated[
        str | None, Form(description="Market region: IN | US | GB (omit for MARKET_REGION env)")
    ] = None,
    processing_mode: Annotated[
        str | None, Form(description="Frontend processing mode: collage | direct")
    ] = None,
    settings: Settings = Depends(get_settings),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
    analyzer: AssetAnalysisService = Depends(get_analyzer),
) -> AnalyzeResponse:
    market = resolve_market(market_region, settings)
    return await _run_analysis(
        images,
        UnifiedViewMethod.COLLAGE,
        locale or market.default_locale,
        market.region,
        settings,
        rate_limiter,
        analyzer,
        processing_mode=processing_mode or "collage",
        api_route="/v1/assets/analyze/collage",
    )


@router.post(
    "/assets/analyze/multi",
    response_model=AnalyzeResponse,
    tags=["Analysis"],
    summary="Analyze asset by sending all angles directly to Gemini (autopilot)",
    description=(
        "Upload 1-10 photos of the same asset. The endpoint sends every image as a "
        "separate part in ONE Gemini call (full per-angle detail) and returns damage "
        "analysis, valuation, token usage, and cost."
    ),
    openapi_extra=MULTI_FILE_OPENAPI,
)
async def analyze_multi(
    images: Annotated[list[UploadFile], File(description="1-10 asset photos")],
    locale: Annotated[str | None, Form(description="Output language")] = None,
    market_region: Annotated[
        str | None, Form(description="Market region: IN | US | GB (omit for MARKET_REGION env)")
    ] = None,
    processing_mode: Annotated[
        str | None, Form(description="Frontend processing mode: collage | direct")
    ] = None,
    settings: Settings = Depends(get_settings),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
    analyzer: AssetAnalysisService = Depends(get_analyzer),
) -> AnalyzeResponse:
    market = resolve_market(market_region, settings)
    return await _run_analysis(
        images,
        UnifiedViewMethod.MULTI_IMAGE,
        locale or market.default_locale,
        market.region,
        settings,
        rate_limiter,
        analyzer,
        processing_mode=processing_mode or "direct",
        api_route="/v1/assets/analyze/multi",
    )
