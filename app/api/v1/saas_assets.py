"""SaaS asset register API."""

from __future__ import annotations

import json
import structlog
from typing import Annotated, Any

from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Body,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import PlainTextResponse

from app.api.v1.history import verify_demo_api_key
from app.config import Settings, get_settings
from app.models.saas_assets import (
    AnalyzeAssetRequest,
    AnalyzeAssetResponse,
    AssetCreateSessionDetail,
    BulkActionResponse,
    BulkAssetIdsRequest,
    CompleteAssetSessionResponse,
    CreateAssetResponse,
    CreateAssetSessionRequest,
    CreateAssetSessionResponse,
    LookupItem,
    LookupListResponse,
    SaasActivityEvent,
    SaasActivityListResponse,
    SaasAnalysisItem,
    SaasAnalysisListResponse,
    SaasAssetDetailResponse,
    SaasAssetListResponse,
    SaasDashboardStats,
    SaveWebDraftRequest,
    RegisterAssetRequest,
    UpdateAssetRequest,
    UpdateAssetResponse,
    WebDraftItem,
    WebDraftListResponse,
)
from app.services.rate_limiter import RateLimiter
from app.services.saas_assets_repository import (
    SaasAssetsRepository,
    SessionCompletedError,
    SessionExpiredError,
    get_saas_assets_repository,
    is_valid_asset_session_token,
    validate_create_metadata,
)
from app.services.saas_lookups import get_lookups
from app.utils.uploads import _finalize_image_bytes

UpdateAssetRequest.model_rebuild()

router = APIRouter(prefix="/saas", tags=["saas"])
logger = structlog.get_logger()

_saas_rate_limiter: RateLimiter | None = None


def get_saas_rate_limiter(settings: Settings = Depends(get_settings)) -> RateLimiter:
    global _saas_rate_limiter
    if _saas_rate_limiter is None:
        _saas_rate_limiter = RateLimiter(settings.saas_assets_rate_limit_per_minute)
    return _saas_rate_limiter


def get_repo(settings: Settings = Depends(get_settings)) -> SaasAssetsRepository:
    return get_saas_assets_repository(settings)


def _require_saas(repo: SaasAssetsRepository) -> None:
    if not repo.enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SaaS asset register is not configured",
        )


async def _read_optional_upload(
    file: UploadFile | None,
    default_name: str,
    settings: Settings,
) -> tuple[bytes | None, str]:
    """Read multipart upload bytes; do not require a non-empty filename."""
    if file is None:
        return None, "image/jpeg"
    raw = await file.read()
    if not raw:
        return None, file.content_type or "image/jpeg"
    _, _, finalized = _finalize_image_bytes(
        raw,
        file.filename or default_name,
        file.content_type,
        settings,
    )
    return finalized, file.content_type or "image/jpeg"


def _asset_create_qr_url(settings: Settings, token: str) -> str | None:
    base = settings.frontend_base_url.strip().rstrip("/")
    if not base:
        return None
    return f"{base}/assets/create/mobile/{token}"


def _parse_metadata_form(
    assetid: str | None = None,
    assetname: str | None = None,
    description: str | None = None,
    tagnumber: str | None = None,
    assetnumber: str | None = None,
    assetclassid: str | None = None,
    assetclassname: str | None = None,
    categoryid: str | None = None,
    categoryname: str | None = None,
    subcategoryid: str | None = None,
    subcategoryname: str | None = None,
    makemodelid: str | None = None,
    makemodelname: str | None = None,
    companyid: str | None = None,
    company: str | None = None,
    customerid: str | None = None,
    assettaggingdetailid: str | None = None,
    cost: str | None = None,
    acquisitiondate: str | None = None,
    metadata: str | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {}
    if metadata:
        try:
            parsed = json.loads(metadata)
            if isinstance(parsed, dict):
                data.update(parsed)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="Invalid metadata JSON") from exc

    locals_map = {
        "assetid": assetid,
        "assetname": assetname,
        "description": description,
        "tagnumber": tagnumber,
        "assetnumber": assetnumber,
        "assetclassid": assetclassid,
        "assetclassname": assetclassname,
        "categoryid": categoryid,
        "categoryname": categoryname,
        "subcategoryid": subcategoryid,
        "subcategoryname": subcategoryname,
        "makemodelid": makemodelid,
        "makemodelname": makemodelname,
        "companyid": companyid,
        "company": company,
        "customerid": customerid,
        "assettaggingdetailid": assettaggingdetailid,
        "cost": cost,
        "acquisitiondate": acquisitiondate,
    }
    for key, value in locals_map.items():
        if value is not None and str(value).strip() != "":
            data[key] = value
    return data


async def _background_analyze(
    settings: Settings, asset_id: str, user_id: int, metadata_patch: dict[str, Any] | None = None
) -> None:
    repo = get_saas_assets_repository(settings)
    try:
        await repo.run_analysis(user_id, asset_id, metadata_patch)
    except Exception as exc:
        logger.exception("saas_background_analyze_failed", asset_id=asset_id, error=str(exc))
        await repo.set_ai_status(asset_id, "error")


@router.get(
    "/lookups",
    response_model=LookupListResponse,
    dependencies=[Depends(verify_demo_api_key)],
)
async def list_lookups(
    type: Annotated[str, Query(description="assetclass|category|subcategory|makemodel|company")],
    parent_id: Annotated[str | None, Query()] = None,
    repo: SaasAssetsRepository = Depends(get_repo),
    rate_limiter: RateLimiter = Depends(get_saas_rate_limiter),
) -> LookupListResponse:
    rate_limiter.check("saas_assets")
    _require_saas(repo)
    try:
        raw = get_lookups(type, parent_id=parent_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    items = [
        LookupItem(
            id=str(i.get("id", "")),
            label=str(i.get("label", i.get("name", ""))),
            parent_id=i.get("parent_id"),
            assetclassid=i.get("assetclassid"),
            categoryid=i.get("categoryid"),
            subcategoryid=i.get("subcategoryid"),
        )
        for i in raw
    ]
    return LookupListResponse(type=type, items=items)


@router.get(
    "/activity",
    response_model=SaasActivityListResponse,
    dependencies=[Depends(verify_demo_api_key)],
)
async def list_activity(
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    repo: SaasAssetsRepository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
    rate_limiter: RateLimiter = Depends(get_saas_rate_limiter),
) -> SaasActivityListResponse:
    rate_limiter.check("saas_assets")
    _require_saas(repo)
    rows = await repo.list_activity(settings.demo_user_id, limit=limit)
    items = [SaasActivityEvent(**r) for r in rows]
    return SaasActivityListResponse(items=items, total=len(items))


@router.get(
    "/assets/stats",
    response_model=SaasDashboardStats,
    dependencies=[Depends(verify_demo_api_key)],
)
async def get_dashboard_stats(
    repo: SaasAssetsRepository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
    rate_limiter: RateLimiter = Depends(get_saas_rate_limiter),
) -> SaasDashboardStats:
    rate_limiter.check("saas_assets")
    _require_saas(repo)
    stats = await repo.get_dashboard_stats(settings.demo_user_id)
    return SaasDashboardStats(**stats)


@router.get(
    "/assets/export.csv",
    response_class=PlainTextResponse,
    dependencies=[Depends(verify_demo_api_key)],
)
async def export_assets_csv(
    q: Annotated[str | None, Query()] = None,
    ai_status: Annotated[str | None, Query()] = None,
    company: Annotated[str | None, Query()] = None,
    repo: SaasAssetsRepository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
    rate_limiter: RateLimiter = Depends(get_saas_rate_limiter),
) -> PlainTextResponse:
    rate_limiter.check("saas_assets")
    _require_saas(repo)
    csv_text = await repo.export_assets_csv(
        settings.demo_user_id, query=q, ai_status=ai_status, company=company
    )
    return PlainTextResponse(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="saas-assets.csv"'},
    )


@router.get(
    "/drafts",
    response_model=WebDraftListResponse,
    dependencies=[Depends(verify_demo_api_key)],
)
async def list_web_drafts(
    repo: SaasAssetsRepository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
    rate_limiter: RateLimiter = Depends(get_saas_rate_limiter),
) -> WebDraftListResponse:
    rate_limiter.check("saas_assets")
    _require_saas(repo)
    items = await repo.list_web_drafts(settings.demo_user_id)
    return WebDraftListResponse(
        items=[WebDraftItem(**i) for i in items],
        total=len(items),
    )


@router.post(
    "/drafts",
    response_model=WebDraftItem,
    dependencies=[Depends(verify_demo_api_key)],
)
async def save_web_draft(
    body: SaveWebDraftRequest,
    draft_id: Annotated[str | None, Query()] = None,
    repo: SaasAssetsRepository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
    rate_limiter: RateLimiter = Depends(get_saas_rate_limiter),
) -> WebDraftItem:
    rate_limiter.check("saas_assets")
    _require_saas(repo)
    try:
        saved = await repo.save_web_draft(
            settings.demo_user_id,
            body.draft_json,
            draft_id=draft_id,
            title=body.title,
            asset_image_path=body.asset_image_path,
            barcode_image_path=body.barcode_image_path,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return WebDraftItem(**saved)


@router.get(
    "/drafts/{draft_id}",
    response_model=WebDraftItem,
    dependencies=[Depends(verify_demo_api_key)],
)
async def get_web_draft(
    draft_id: str,
    repo: SaasAssetsRepository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
    rate_limiter: RateLimiter = Depends(get_saas_rate_limiter),
) -> WebDraftItem:
    rate_limiter.check("saas_assets")
    _require_saas(repo)
    draft = await repo.get_web_draft(settings.demo_user_id, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return WebDraftItem(**draft)


@router.delete(
    "/drafts/{draft_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(verify_demo_api_key)],
)
async def delete_web_draft(
    draft_id: str,
    repo: SaasAssetsRepository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
    rate_limiter: RateLimiter = Depends(get_saas_rate_limiter),
) -> None:
    rate_limiter.check("saas_assets")
    _require_saas(repo)
    deleted = await repo.delete_web_draft(settings.demo_user_id, draft_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Draft not found")


@router.get(
    "/assets",
    response_model=SaasAssetListResponse,
    dependencies=[Depends(verify_demo_api_key)],
)
async def list_assets(
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    q: Annotated[str | None, Query(description="Search asset name, id, tag, company")] = None,
    ai_status: Annotated[str | None, Query()] = None,
    company: Annotated[str | None, Query()] = None,
    sort: Annotated[str, Query()] = "created_at",
    order: Annotated[str, Query(pattern="^(asc|desc)$")] = "desc",
    repo: SaasAssetsRepository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
    rate_limiter: RateLimiter = Depends(get_saas_rate_limiter),
) -> SaasAssetListResponse:
    rate_limiter.check("saas_assets")
    _require_saas(repo)
    items, total = await repo.list_assets(
        settings.demo_user_id,
        limit=limit,
        offset=offset,
        query=q,
        ai_status=ai_status,
        company=company,
        sort=sort,
        order=order,
    )
    return SaasAssetListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/assets/{asset_id}",
    response_model=SaasAssetDetailResponse,
    dependencies=[Depends(verify_demo_api_key)],
)
async def get_asset(
    asset_id: UUID,
    repo: SaasAssetsRepository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
    rate_limiter: RateLimiter = Depends(get_saas_rate_limiter),
) -> SaasAssetDetailResponse:
    rate_limiter.check("saas_assets")
    _require_saas(repo)
    detail = await repo.get_asset(settings.demo_user_id, str(asset_id))
    if not detail:
        raise HTTPException(status_code=404, detail="Asset not found")
    return detail


@router.post(
    "/assets",
    response_model=CreateAssetResponse,
    dependencies=[Depends(verify_demo_api_key)],
)
async def create_asset(
    background_tasks: BackgroundTasks,
    assetimage: Annotated[UploadFile, File()],
    barcodeimage: Annotated[UploadFile | None, File()] = None,
    assetid: Annotated[str | None, Form()] = None,
    assetname: Annotated[str | None, Form()] = None,
    description: Annotated[str | None, Form()] = None,
    tagnumber: Annotated[str | None, Form()] = None,
    assetnumber: Annotated[str | None, Form()] = None,
    assetclassid: Annotated[str | None, Form()] = None,
    assetclassname: Annotated[str | None, Form()] = None,
    categoryid: Annotated[str | None, Form()] = None,
    categoryname: Annotated[str | None, Form()] = None,
    subcategoryid: Annotated[str | None, Form()] = None,
    subcategoryname: Annotated[str | None, Form()] = None,
    makemodelid: Annotated[str | None, Form()] = None,
    makemodelname: Annotated[str | None, Form()] = None,
    companyid: Annotated[str | None, Form()] = None,
    company: Annotated[str | None, Form()] = None,
    customerid: Annotated[str | None, Form()] = None,
    assettaggingdetailid: Annotated[str | None, Form()] = None,
    cost: Annotated[str | None, Form()] = None,
    acquisitiondate: Annotated[str | None, Form()] = None,
    metadata: Annotated[str | None, Form()] = None,
    repo: SaasAssetsRepository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
    rate_limiter: RateLimiter = Depends(get_saas_rate_limiter),
) -> CreateAssetResponse:
    rate_limiter.check("saas_assets")
    _require_saas(repo)

    meta = _parse_metadata_form(
        assetid=assetid,
        assetname=assetname,
        description=description,
        tagnumber=tagnumber,
        assetnumber=assetnumber,
        assetclassid=assetclassid,
        assetclassname=assetclassname,
        categoryid=categoryid,
        categoryname=categoryname,
        subcategoryid=subcategoryid,
        subcategoryname=subcategoryname,
        makemodelid=makemodelid,
        makemodelname=makemodelname,
        companyid=companyid,
        company=company,
        customerid=customerid,
        assettaggingdetailid=assettaggingdetailid,
        cost=cost,
        acquisitiondate=acquisitiondate,
        metadata=metadata,
    )

    try:
        raw = await assetimage.read()
        _, filename, asset_bytes = _finalize_image_bytes(
            raw,
            assetimage.filename or "asset.jpg",
            assetimage.content_type,
            settings,
        )
        asset_mime = assetimage.content_type or "image/jpeg"
        barcode_bytes = None
        barcode_mime = "image/jpeg"
        if barcodeimage and barcodeimage.filename:
            raw_barcode = await barcodeimage.read()
            _, _, barcode_bytes = _finalize_image_bytes(
                raw_barcode,
                barcodeimage.filename or "barcode.jpg",
                barcodeimage.content_type,
                settings,
            )
            barcode_mime = barcodeimage.content_type or "image/jpeg"
        meta["_has_asset_image"] = True
        validate_create_metadata(meta)
        result = await repo.create_asset(
            settings.demo_user_id,
            meta,
            asset_bytes,
            barcode_bytes,
            asset_mime=asset_mime,
            barcode_mime=barcode_mime,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("saas_create_asset_failed", error=str(exc))
        raise HTTPException(status_code=503, detail="Failed to create asset") from exc

    await repo.set_ai_status(result.id, "analyzing")
    background_tasks.add_task(_background_analyze, settings, result.id, settings.demo_user_id)
    return CreateAssetResponse(id=result.id, assetid=result.assetid, ai_status="analyzing")


@router.post(
    "/assets/register",
    response_model=CreateAssetResponse,
    dependencies=[Depends(verify_demo_api_key)],
)
async def register_asset(
    body: RegisterAssetRequest,
    repo: SaasAssetsRepository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
    rate_limiter: RateLimiter = Depends(get_saas_rate_limiter),
) -> CreateAssetResponse:
    """Register asset metadata without photos. AI analysis runs after images are uploaded."""
    rate_limiter.check("saas_assets")
    _require_saas(repo)
    metadata = body.model_dump(exclude_unset=True)
    try:
        return await repo.register_asset(settings.demo_user_id, metadata)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("saas_register_asset_failed", error=str(exc))
        raise HTTPException(status_code=503, detail="Failed to register asset") from exc


@router.patch(
    "/assets/{asset_id}",
    response_model=UpdateAssetResponse,
    dependencies=[Depends(verify_demo_api_key)],
)
async def update_asset(
    asset_id: UUID,
    background_tasks: BackgroundTasks,
    body: UpdateAssetRequest = Body(),
    reanalyze: Annotated[bool, Query()] = False,
    repo: SaasAssetsRepository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
    rate_limiter: RateLimiter = Depends(get_saas_rate_limiter),
) -> UpdateAssetResponse:
    rate_limiter.check("saas_assets")
    _require_saas(repo)
    metadata = body.model_dump(exclude_unset=True)
    if not metadata:
        detail = await repo.get_asset(settings.demo_user_id, str(asset_id))
        if not detail:
            raise HTTPException(status_code=404, detail="Asset not found")
        return UpdateAssetResponse(asset=detail.asset)
    updated = await repo.update_asset(settings.demo_user_id, str(asset_id), metadata)
    if not updated:
        raise HTTPException(status_code=404, detail="Asset not found")
    if reanalyze:
        await repo.set_ai_status(str(asset_id), "analyzing")
        background_tasks.add_task(
            _background_analyze, settings, str(asset_id), settings.demo_user_id, None
        )
        detail = await repo.get_asset(settings.demo_user_id, str(asset_id))
        if detail:
            return UpdateAssetResponse(asset=detail.asset)
    return UpdateAssetResponse(asset=updated)


@router.post(
    "/assets/{asset_id}/images",
    response_model=UpdateAssetResponse,
    dependencies=[Depends(verify_demo_api_key)],
)
async def upload_asset_images(
    asset_id: UUID,
    background_tasks: BackgroundTasks,
    assetimage: Annotated[UploadFile | None, File()] = None,
    barcodeimage: Annotated[UploadFile | None, File()] = None,
    session_token: Annotated[str | None, Query()] = None,
    reanalyze: Annotated[bool, Query()] = True,
    repo: SaasAssetsRepository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
    rate_limiter: RateLimiter = Depends(get_saas_rate_limiter),
) -> UpdateAssetResponse:
    """Upload photos to an existing asset. Starts AI analysis when asset image is provided."""
    rate_limiter.check("saas_assets")
    _require_saas(repo)

    detail = await repo.get_asset(settings.demo_user_id, str(asset_id))
    if not detail:
        raise HTTPException(status_code=404, detail="Asset not found")

    has_existing_asset_image = bool(detail.asset.asset_image_url)
    token = (session_token or "").strip() or None

    if not assetimage and not barcodeimage and not token:
        raise HTTPException(
            status_code=400,
            detail="Provide assetimage, barcodeimage, or session_token",
        )

    asset_bytes = None
    asset_mime = "image/jpeg"
    barcode_bytes = None
    barcode_mime = "image/jpeg"
    used_session = False

    try:
        asset_bytes, asset_mime = await _read_optional_upload(assetimage, "asset.jpg", settings)
        barcode_bytes, barcode_mime = await _read_optional_upload(
            barcodeimage, "barcode.jpg", settings
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if token and not asset_bytes and not barcode_bytes:
        if not is_valid_asset_session_token(token):
            raise HTTPException(status_code=400, detail="Invalid session token")
        try:
            updated = await repo.apply_session_images_to_asset(
                settings.demo_user_id,
                str(asset_id),
                token,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not updated:
            raise HTTPException(status_code=404, detail="Asset not found")
        used_session = True
    elif not asset_bytes and not barcode_bytes:
        raise HTTPException(status_code=400, detail="Empty file upload")
    elif not asset_bytes and not has_existing_asset_image:
        raise HTTPException(status_code=400, detail="Asset image is required")
    else:
        updated = await repo.update_asset(
            settings.demo_user_id,
            str(asset_id),
            {},
            asset_image=asset_bytes,
            barcode_image=barcode_bytes,
            asset_mime=asset_mime,
            barcode_mime=barcode_mime,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Asset not found")

    await repo.log_activity(
        settings.demo_user_id,
        "photos_uploaded",
        f"Photos added for {updated.assetname or updated.assetid}",
        asset_id=str(asset_id),
        assetname=updated.assetname,
        assetid=updated.assetid,
    )

    got_asset_image = asset_bytes is not None or used_session or has_existing_asset_image
    should_analyze = reanalyze and got_asset_image
    if should_analyze:
        await repo.set_ai_status(str(asset_id), "analyzing")
        background_tasks.add_task(
            _background_analyze, settings, str(asset_id), settings.demo_user_id, None
        )
        detail = await repo.get_asset(settings.demo_user_id, str(asset_id))
        if detail:
            return UpdateAssetResponse(asset=detail.asset)

    return UpdateAssetResponse(asset=updated)


@router.delete(
    "/assets/{asset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(verify_demo_api_key)],
)
async def delete_asset(
    asset_id: UUID,
    repo: SaasAssetsRepository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
    rate_limiter: RateLimiter = Depends(get_saas_rate_limiter),
) -> None:
    rate_limiter.check("saas_assets")
    _require_saas(repo)
    deleted = await repo.delete_asset(settings.demo_user_id, str(asset_id))
    if not deleted:
        raise HTTPException(status_code=404, detail="Asset not found")


@router.post(
    "/assets/bulk-delete",
    response_model=BulkActionResponse,
    dependencies=[Depends(verify_demo_api_key)],
)
async def bulk_delete_assets(
    body: BulkAssetIdsRequest,
    repo: SaasAssetsRepository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
    rate_limiter: RateLimiter = Depends(get_saas_rate_limiter),
) -> BulkActionResponse:
    rate_limiter.check("saas_assets")
    _require_saas(repo)
    count = await repo.bulk_delete(settings.demo_user_id, body.asset_ids)
    return BulkActionResponse(processed=count, asset_ids=body.asset_ids)


@router.post(
    "/assets/bulk-analyze",
    response_model=BulkActionResponse,
    dependencies=[Depends(verify_demo_api_key)],
)
async def bulk_analyze_assets(
    body: BulkAssetIdsRequest,
    background_tasks: BackgroundTasks,
    repo: SaasAssetsRepository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
    rate_limiter: RateLimiter = Depends(get_saas_rate_limiter),
) -> BulkActionResponse:
    rate_limiter.check("saas_assets")
    _require_saas(repo)
    queued = await repo.bulk_analyze(settings.demo_user_id, body.asset_ids)
    for aid in queued:
        background_tasks.add_task(
            _background_analyze, settings, aid, settings.demo_user_id, None
        )
    return BulkActionResponse(processed=len(queued), asset_ids=queued)


@router.post(
    "/assets/{asset_id}/analyze",
    response_model=AnalyzeAssetResponse,
    dependencies=[Depends(verify_demo_api_key)],
)
async def analyze_asset(
    asset_id: UUID,
    background_tasks: BackgroundTasks,
    body: AnalyzeAssetRequest | None = Body(default=None),
    repo: SaasAssetsRepository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
    rate_limiter: RateLimiter = Depends(get_saas_rate_limiter),
) -> AnalyzeAssetResponse:
    rate_limiter.check("saas_assets")
    _require_saas(repo)
    detail = await repo.get_asset(settings.demo_user_id, str(asset_id))
    if not detail:
        raise HTTPException(status_code=404, detail="Asset not found")
    patch = body.metadata_patch if body else None
    await repo.set_ai_status(str(asset_id), "analyzing")
    background_tasks.add_task(
        _background_analyze, settings, str(asset_id), settings.demo_user_id, patch
    )
    return AnalyzeAssetResponse(asset_id=str(asset_id), ai_status="analyzing")


@router.get(
    "/assets/{asset_id}/analyses",
    response_model=SaasAnalysisListResponse,
    dependencies=[Depends(verify_demo_api_key)],
)
async def list_asset_analyses(
    asset_id: UUID,
    repo: SaasAssetsRepository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
    rate_limiter: RateLimiter = Depends(get_saas_rate_limiter),
) -> SaasAnalysisListResponse:
    rate_limiter.check("saas_assets")
    _require_saas(repo)
    detail = await repo.get_asset(settings.demo_user_id, str(asset_id))
    if not detail:
        raise HTTPException(status_code=404, detail="Asset not found")
    items = await repo.list_analyses(settings.demo_user_id, str(asset_id))
    return SaasAnalysisListResponse(items=items, total=len(items))


@router.get(
    "/assets/{asset_id}/analyses/{analysis_id}",
    response_model=SaasAnalysisItem,
    dependencies=[Depends(verify_demo_api_key)],
)
async def get_asset_analysis(
    asset_id: UUID,
    analysis_id: str,
    repo: SaasAssetsRepository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
    rate_limiter: RateLimiter = Depends(get_saas_rate_limiter),
) -> SaasAnalysisItem:
    rate_limiter.check("saas_assets")
    _require_saas(repo)
    item = await repo.get_analysis(settings.demo_user_id, str(asset_id), analysis_id)
    if not item:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return item


@router.post(
    "/asset-sessions",
    response_model=CreateAssetSessionResponse,
    dependencies=[Depends(verify_demo_api_key)],
)
async def create_asset_session(
    body: CreateAssetSessionRequest,
    repo: SaasAssetsRepository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
    rate_limiter: RateLimiter = Depends(get_saas_rate_limiter),
) -> CreateAssetSessionResponse:
    rate_limiter.check("saas_asset_sessions")
    _require_saas(repo)
    detail = await repo.create_asset_session(settings.demo_user_id, body.draft_json)
    return CreateAssetSessionResponse(
        session_token=detail.session_token,
        status=detail.status,
        expires_at=detail.expires_at,
        qr_url=_asset_create_qr_url(settings, detail.session_token),
    )


@router.get(
    "/asset-sessions/{token}",
    response_model=AssetCreateSessionDetail,
    dependencies=[Depends(verify_demo_api_key)],
)
async def get_asset_session(
    token: str,
    repo: SaasAssetsRepository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
    rate_limiter: RateLimiter = Depends(get_saas_rate_limiter),
) -> AssetCreateSessionDetail:
    rate_limiter.check("saas_asset_sessions")
    _require_saas(repo)
    if not is_valid_asset_session_token(token):
        raise HTTPException(status_code=400, detail="Invalid session token")
    try:
        detail = await repo.get_asset_session(token)
    except SessionCompletedError as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    except SessionExpiredError as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    if not detail:
        raise HTTPException(status_code=404, detail="Session not found")
    return detail


@router.post(
    "/asset-sessions/{token}/images",
    response_model=AssetCreateSessionDetail,
    dependencies=[Depends(verify_demo_api_key)],
)
async def upload_asset_session_image(
    token: str,
    assetimage: Annotated[UploadFile | None, File()] = None,
    barcodeimage: Annotated[UploadFile | None, File()] = None,
    repo: SaasAssetsRepository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
    rate_limiter: RateLimiter = Depends(get_saas_rate_limiter),
) -> AssetCreateSessionDetail:
    rate_limiter.check("saas_asset_sessions")
    _require_saas(repo)
    if not is_valid_asset_session_token(token):
        raise HTTPException(status_code=400, detail="Invalid session token")

    if not assetimage and not barcodeimage:
        raise HTTPException(status_code=400, detail="Provide assetimage or barcodeimage")

    try:
        asset_bytes, asset_mime = await _read_optional_upload(assetimage, "asset.jpg", settings)
        if asset_bytes:
            return await repo.upload_session_image(
                token, "asset", asset_bytes, mime_type=asset_mime
            )
        barcode_bytes, barcode_mime = await _read_optional_upload(
            barcodeimage, "barcode.jpg", settings
        )
        if barcode_bytes:
            return await repo.upload_session_image(
                token, "barcode", barcode_bytes, mime_type=barcode_mime
            )
    except SessionCompletedError as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    except SessionExpiredError as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    raise HTTPException(status_code=400, detail="Empty file upload")


@router.post(
    "/asset-sessions/{token}/complete",
    response_model=CompleteAssetSessionResponse,
    dependencies=[Depends(verify_demo_api_key)],
)
async def complete_asset_session(
    token: str,
    background_tasks: BackgroundTasks,
    assetid: Annotated[str | None, Form()] = None,
    assetname: Annotated[str | None, Form()] = None,
    description: Annotated[str | None, Form()] = None,
    tagnumber: Annotated[str | None, Form()] = None,
    assetnumber: Annotated[str | None, Form()] = None,
    assetclassid: Annotated[str | None, Form()] = None,
    assetclassname: Annotated[str | None, Form()] = None,
    categoryid: Annotated[str | None, Form()] = None,
    categoryname: Annotated[str | None, Form()] = None,
    subcategoryid: Annotated[str | None, Form()] = None,
    subcategoryname: Annotated[str | None, Form()] = None,
    makemodelid: Annotated[str | None, Form()] = None,
    makemodelname: Annotated[str | None, Form()] = None,
    companyid: Annotated[str | None, Form()] = None,
    company: Annotated[str | None, Form()] = None,
    customerid: Annotated[str | None, Form()] = None,
    assettaggingdetailid: Annotated[str | None, Form()] = None,
    cost: Annotated[str | None, Form()] = None,
    acquisitiondate: Annotated[str | None, Form()] = None,
    metadata: Annotated[str | None, Form()] = None,
    repo: SaasAssetsRepository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
    rate_limiter: RateLimiter = Depends(get_saas_rate_limiter),
) -> CompleteAssetSessionResponse:
    rate_limiter.check("saas_asset_sessions")
    _require_saas(repo)
    if not is_valid_asset_session_token(token):
        raise HTTPException(status_code=400, detail="Invalid session token")

    meta = _parse_metadata_form(
        assetid=assetid,
        assetname=assetname,
        description=description,
        tagnumber=tagnumber,
        assetnumber=assetnumber,
        assetclassid=assetclassid,
        assetclassname=assetclassname,
        categoryid=categoryid,
        categoryname=categoryname,
        subcategoryid=subcategoryid,
        subcategoryname=subcategoryname,
        makemodelid=makemodelid,
        makemodelname=makemodelname,
        companyid=companyid,
        company=company,
        customerid=customerid,
        assettaggingdetailid=assettaggingdetailid,
        cost=cost,
        acquisitiondate=acquisitiondate,
        metadata=metadata,
    )

    try:
        result = await repo.complete_asset_session(token, meta)
    except SessionCompletedError as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    except SessionExpiredError as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("saas_complete_session_failed", error=str(exc))
        raise HTTPException(status_code=503, detail="Failed to create asset") from exc

    background_tasks.add_task(
        _background_analyze, settings, result.asset_id, settings.demo_user_id
    )
    return result
