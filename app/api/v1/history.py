"""History CRUD — backed by Supabase (demo user_id=100)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from app.config import Settings, get_settings
from app.models.history import DeleteHistoryResponse, HistoryDetailResponse, HistoryListResponse
from app.services.history_repository import HistoryRepository, get_history_repository, is_valid_entry_id
from app.services.rate_limiter import RateLimiter

router = APIRouter()

_history_rate_limiter: RateLimiter | None = None


def get_history_rate_limiter(settings: Settings = Depends(get_settings)) -> RateLimiter:
    global _history_rate_limiter
    if _history_rate_limiter is None:
        _history_rate_limiter = RateLimiter(settings.history_rate_limit_per_minute)
    return _history_rate_limiter


def verify_demo_api_key(
    x_demo_key: Annotated[str | None, Header(alias="X-Demo-Key")] = None,
    settings: Settings = Depends(get_settings),
) -> None:
    expected = settings.demo_api_key.strip()
    if not expected:
        return
    if not x_demo_key or x_demo_key.strip() != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing demo API key",
        )


def get_repo(settings: Settings = Depends(get_settings)) -> HistoryRepository:
    return get_history_repository(settings)


def _require_persist(repo: HistoryRepository) -> None:
    if not repo.enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="History persistence is not configured",
        )


@router.get(
    "/history",
    response_model=HistoryListResponse,
    tags=["History"],
    dependencies=[Depends(verify_demo_api_key)],
)
async def list_history(
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    q: Annotated[str | None, Query(description="Search asset name or tag")] = None,
    repo: HistoryRepository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
    rate_limiter: RateLimiter = Depends(get_history_rate_limiter),
) -> HistoryListResponse:
    rate_limiter.check("history")
    _require_persist(repo)
    items, total = await repo.list_analyses(
        user_id=settings.demo_user_id,
        limit=limit,
        offset=offset,
        query=q,
    )
    return HistoryListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/history/{entry_id}",
    response_model=HistoryDetailResponse,
    tags=["History"],
    dependencies=[Depends(verify_demo_api_key)],
)
async def get_history_entry(
    entry_id: str,
    repo: HistoryRepository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
    rate_limiter: RateLimiter = Depends(get_history_rate_limiter),
) -> HistoryDetailResponse:
    rate_limiter.check("history")
    _require_persist(repo)
    if not is_valid_entry_id(entry_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid entry id")
    detail = await repo.get_analysis(user_id=settings.demo_user_id, entry_id=entry_id)
    if not detail:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found")
    return detail


@router.delete(
    "/history/{entry_id}",
    response_model=DeleteHistoryResponse,
    tags=["History"],
    dependencies=[Depends(verify_demo_api_key)],
)
async def delete_history_entry(
    entry_id: str,
    repo: HistoryRepository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
    rate_limiter: RateLimiter = Depends(get_history_rate_limiter),
) -> DeleteHistoryResponse:
    rate_limiter.check("history")
    _require_persist(repo)
    if not is_valid_entry_id(entry_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid entry id")
    deleted = await repo.delete_analysis(user_id=settings.demo_user_id, entry_id=entry_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found")
    return DeleteHistoryResponse(entry_id=entry_id, deleted=True)
