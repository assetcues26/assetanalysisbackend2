"""Pydantic models for SaaS asset register module."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SaasAssetSummary(BaseModel):
    id: str
    assetid: str
    assetname: str | None = None
    description: str | None = None
    tagnumber: str | None = None
    assetnumber: str | None = None
    assetclassid: str | None = None
    assetclassname: str | None = None
    categoryid: str | None = None
    categoryname: str | None = None
    subcategoryid: str | None = None
    subcategoryname: str | None = None
    makemodelid: str | None = None
    makemodelname: str | None = None
    companyid: str | None = None
    company: str | None = None
    customerid: str | None = None
    assettaggingdetailid: str | None = None
    cost: float | None = None
    acquisitiondate: str | None = None
    ai_status: str = "pending"
    asset_image_url: str | None = None
    barcode_image_url: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    # Latest analysis summary fields for dashboard columns
    detected_asset: str | None = None
    condition: str | None = None
    namedescriptionmatch: str | None = None
    subcatmodelmatch: str | None = None
    detectedtagnumbermatch: str | None = None
    costmatch: str | None = None
    datematch: str | None = None
    latest_analysis_id: str | None = None
    failure_summary: dict[str, Any] | None = None


class SaasAssetListResponse(BaseModel):
    items: list[SaasAssetSummary]
    total: int
    limit: int
    offset: int


class SaasAnalysisItem(BaseModel):
    id: str
    asset_id: str
    request_id: str | None = None
    ai_status: str
    failure_summary: dict[str, Any] | None = None
    response_time_seconds: float | None = None
    created_at: str | None = None
    response_json: dict[str, Any] | None = None


class SaasAssetDetailResponse(BaseModel):
    asset: SaasAssetSummary
    latest_analysis: SaasAnalysisItem | None = None


class SaasAnalysisListResponse(BaseModel):
    items: list[SaasAnalysisItem]
    total: int


class CreateAssetSessionRequest(BaseModel):
    draft_json: dict[str, Any] = Field(default_factory=dict)


class CreateAssetSessionResponse(BaseModel):
    session_token: str
    status: str
    expires_at: str
    qr_url: str | None = None


class AssetCreateSessionDetail(BaseModel):
    session_token: str
    status: str
    draft_json: dict[str, Any] = Field(default_factory=dict)
    asset_image_url: str | None = None
    barcode_image_url: str | None = None
    expires_at: str
    created_asset_id: str | None = None


class CompleteAssetSessionResponse(BaseModel):
    asset_id: str
    assetid: str
    ai_status: str = "analyzing"


class AnalyzeAssetResponse(BaseModel):
    asset_id: str
    ai_status: str


class CreateAssetResponse(BaseModel):
    id: str
    assetid: str
    ai_status: str = "analyzing"


class UpdateAssetRequest(BaseModel):
    assetid: str | None = None
    assetname: str | None = None
    description: str | None = None
    tagnumber: str | None = None
    assetnumber: str | None = None
    assetclassid: str | None = None
    assetclassname: str | None = None
    categoryid: str | None = None
    categoryname: str | None = None
    subcategoryid: str | None = None
    subcategoryname: str | None = None
    makemodelid: str | None = None
    makemodelname: str | None = None
    companyid: str | None = None
    company: str | None = None
    customerid: str | None = None
    assettaggingdetailid: str | None = None
    cost: str | float | None = None
    acquisitiondate: str | None = None


class UpdateAssetResponse(BaseModel):
    asset: SaasAssetSummary


class BulkAssetIdsRequest(BaseModel):
    asset_ids: list[str] = Field(min_length=1)


class BulkActionResponse(BaseModel):
    processed: int
    asset_ids: list[str]


class SaasDashboardStats(BaseModel):
    total: int = 0
    pass_count: int = 0
    fail_count: int = 0
    pending: int = 0
    error: int = 0
    analyzing: int = 0


class SaasActivityEvent(BaseModel):
    id: str
    event_type: str
    asset_id: str | None = None
    assetname: str | None = None
    assetid: str | None = None
    ai_status: str | None = None
    message: str
    created_at: str


class SaasActivityListResponse(BaseModel):
    items: list[SaasActivityEvent]
    total: int


class LookupItem(BaseModel):
    id: str
    label: str
    parent_id: str | None = None
    assetclassid: str | None = None
    categoryid: str | None = None
    subcategoryid: str | None = None


class LookupListResponse(BaseModel):
    type: str
    items: list[LookupItem]


class WebDraftItem(BaseModel):
    id: str
    title: str | None = None
    draft_json: dict[str, Any] = Field(default_factory=dict)
    asset_image_url: str | None = None
    barcode_image_url: str | None = None
    updated_at: str | None = None


class WebDraftListResponse(BaseModel):
    items: list[WebDraftItem]
    total: int


class SaveWebDraftRequest(BaseModel):
    title: str | None = None
    draft_json: dict[str, Any] = Field(default_factory=dict)
    asset_image_path: str | None = None
    barcode_image_path: str | None = None


class AnalyzeAssetRequest(BaseModel):
    metadata_patch: dict[str, Any] | None = None
