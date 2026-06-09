"""Cross-device capture session API."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile, status

from app.api.v1.history import verify_demo_api_key
from app.config import Settings, get_settings
from app.models.capture_session import (
    AnalyzeSessionResponse,
    CreateSessionRequest,
    CreateSessionResponse,
    SessionDetailResponse,
)
from app.services.analyzer import AssetAnalysisService
from app.services.capture_session_repository import (
    CaptureSessionRepository,
    get_capture_session_repository,
    is_valid_session_token,
)
from app.services.gemini import GeminiService
from app.services.rate_limiter import RateLimiter
from app.utils.uploads import _finalize_image_bytes

router = APIRouter()

_session_rate_limiter: RateLimiter | None = None
_analyzer: AssetAnalysisService | None = None


def get_session_rate_limiter(settings: Settings = Depends(get_settings)) -> RateLimiter:
    global _session_rate_limiter
    if _session_rate_limiter is None:
        _session_rate_limiter = RateLimiter(settings.session_rate_limit_per_minute)
    return _session_rate_limiter


def get_analyzer(settings: Settings = Depends(get_settings)) -> AssetAnalysisService:
    global _analyzer
    if _analyzer is None:
        _analyzer = AssetAnalysisService(settings=settings, gemini=GeminiService(settings))
    return _analyzer


def get_repo(settings: Settings = Depends(get_settings)) -> CaptureSessionRepository:
    return get_capture_session_repository(settings)


def _require_sessions(repo: CaptureSessionRepository) -> None:
    if not repo.enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Capture sessions are not configured",
        )


def _qr_url(settings: Settings, token: str) -> str | None:
    base = settings.frontend_base_url.strip().rstrip("/")
    if not base:
        return None
    return f"{base}/scan/{token}"


@router.post(
    "/sessions",
    response_model=CreateSessionResponse,
    tags=["Sessions"],
    dependencies=[Depends(verify_demo_api_key)],
)
async def create_session(
    body: CreateSessionRequest,
    repo: CaptureSessionRepository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
    rate_limiter: RateLimiter = Depends(get_session_rate_limiter),
) -> CreateSessionResponse:
    rate_limiter.check("sessions")
    _require_sessions(repo)
    detail = await repo.create_session(
        user_id=settings.demo_user_id,
        processing_mode=body.processing_mode,
    )
    return CreateSessionResponse(
        session_token=detail.session_token,
        status=detail.status,
        processing_mode=detail.processing_mode,
        image_count=detail.image_count,
        expires_at=detail.expires_at,
        images=detail.images,
    )


@router.get(
    "/sessions/{token}",
    response_model=SessionDetailResponse,
    tags=["Sessions"],
    dependencies=[Depends(verify_demo_api_key)],
)
async def get_session(
    token: str,
    repo: CaptureSessionRepository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
    rate_limiter: RateLimiter = Depends(get_session_rate_limiter),
) -> SessionDetailResponse:
    rate_limiter.check("sessions")
    _require_sessions(repo)
    if not is_valid_session_token(token):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid session token")
    detail = await repo.get_session(token=token, user_id=settings.demo_user_id)
    if not detail:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return detail


@router.post(
    "/sessions/{token}/images",
    response_model=SessionDetailResponse,
    tags=["Sessions"],
    dependencies=[Depends(verify_demo_api_key)],
)
async def upload_session_image(
    token: str,
    images: Annotated[list[UploadFile], File(description="1+ images")],
    source: Annotated[str, Form(description="laptop or mobile")] = "mobile",
    repo: CaptureSessionRepository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
    rate_limiter: RateLimiter = Depends(get_session_rate_limiter),
) -> SessionDetailResponse:
    rate_limiter.check("sessions")
    _require_sessions(repo)
    if not is_valid_session_token(token):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid session token")

    src = "laptop" if source == "laptop" else "mobile"
    real = [img for img in (images or []) if img is not None and (img.filename or img.content_type)]
    if not real:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No images provided")

    detail: SessionDetailResponse | None = None
    for upload in real:
        raw = await upload.read()
        try:
            _, filename, finalized = _finalize_image_bytes(
                raw,
                upload.filename or "image.jpg",
                upload.content_type,
                settings,
            )
            detail = await repo.upload_image(
                token=token,
                user_id=settings.demo_user_id,
                raw=finalized,
                filename=filename,
                mime_type=upload.content_type or "image/jpeg",
                source=src,
            )
        except ValueError as exc:
            msg = str(exc)
            if "Maximum" in msg or "exceed" in msg.lower():
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg) from exc
            if "Session is" in msg or "cannot add" in msg:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=msg) from exc
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg) from exc

    return detail  # type: ignore[return-value]


@router.delete(
    "/sessions/{token}/images/{image_id}",
    response_model=SessionDetailResponse,
    tags=["Sessions"],
    dependencies=[Depends(verify_demo_api_key)],
)
async def delete_session_image(
    token: str,
    image_id: str,
    repo: CaptureSessionRepository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
    rate_limiter: RateLimiter = Depends(get_session_rate_limiter),
) -> SessionDetailResponse:
    rate_limiter.check("sessions")
    _require_sessions(repo)
    if not is_valid_session_token(token):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid session token")
    try:
        return await repo.delete_image(
            token=token,
            user_id=settings.demo_user_id,
            image_id=image_id,
        )
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg) from exc
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=msg) from exc


@router.post(
    "/sessions/{token}/analyze",
    response_model=AnalyzeSessionResponse,
    tags=["Sessions"],
    dependencies=[Depends(verify_demo_api_key)],
)
async def analyze_session(
    token: str,
    locale: Annotated[str, Form(description="Output language")] = "en-IN",
    repo: CaptureSessionRepository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
    analyzer: AssetAnalysisService = Depends(get_analyzer),
    rate_limiter: RateLimiter = Depends(get_session_rate_limiter),
) -> AnalyzeSessionResponse:
    rate_limiter.check("sessions")
    _require_sessions(repo)
    if not is_valid_session_token(token):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid session token")

    detail, error = await repo.analyze_session(
        token=token,
        user_id=settings.demo_user_id,
        analyzer=analyzer,
        locale=locale,
    )
    if error and not detail:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=error)
    if error and detail and detail.status == "active":
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=error) from None
    if not detail:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    if detail.status == "analyzing":
        return AnalyzeSessionResponse(
            session_token=detail.session_token,
            status="analyzing",
        )
    if detail.status == "completed":
        return AnalyzeSessionResponse(
            session_token=detail.session_token,
            status="completed",
            entry_id=detail.entry_id,
            saved_to_db=bool(detail.entry_id),
        )
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=f"Session is {detail.status}",
    )
