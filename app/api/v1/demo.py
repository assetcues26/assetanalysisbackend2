"""Demo maintenance endpoints (pre-demo reset, no schema changes)."""

import structlog
from fastapi import APIRouter, Depends, HTTPException, status

from app.api.v1.history import verify_demo_api_key
from app.config import Settings, get_settings
from app.models.demo import ClearDemoDataResponse
from app.services.demo_data_repository import DemoDataRepository, get_demo_data_repository
from app.services.rate_limiter import RateLimiter

router = APIRouter()
logger = structlog.get_logger()

_demo_rate_limiter: RateLimiter | None = None


def get_demo_rate_limiter(settings: Settings = Depends(get_settings)) -> RateLimiter:
    global _demo_rate_limiter
    if _demo_rate_limiter is None:
        _demo_rate_limiter = RateLimiter(settings.history_rate_limit_per_minute)
    return _demo_rate_limiter


def get_repo(settings: Settings = Depends(get_settings)) -> DemoDataRepository:
    return get_demo_data_repository(settings)


def _require_persist(repo: DemoDataRepository) -> None:
    if not repo.enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database persistence is not configured",
        )


@router.post(
    "/demo/clear-data",
    response_model=ClearDemoDataResponse,
    tags=["Demo"],
    dependencies=[Depends(verify_demo_api_key)],
)
async def clear_demo_data(
    repo: DemoDataRepository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
    rate_limiter: RateLimiter = Depends(get_demo_rate_limiter),
) -> ClearDemoDataResponse:
    """Delete all demo user rows and storage files. Does not drop tables or migrations."""
    rate_limiter.check("demo")
    _require_persist(repo)
    try:
        return await repo.clear_demo_data(user_id=settings.demo_user_id)
    except Exception as exc:
        logger.exception("clear_demo_data_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not clear demo data. Try again shortly.",
        ) from exc
