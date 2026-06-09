"""History / persistence API models."""

from pydantic import BaseModel, Field


class ImageUrls(BaseModel):
    preview_urls: list[str] = Field(default_factory=list)
    merged_image_url: str | None = None


class HistoryListItem(BaseModel):
    entry_id: str
    request_id: str
    asset_name: str | None = None
    asset_tag: str | None = None
    condition_grade: str | None = None
    analysis_method: str | None = None
    processing_mode: str | None = None
    images_analyzed: int = 0
    processed_at: str
    preview_url: str | None = None


class HistoryListResponse(BaseModel):
    items: list[HistoryListItem] = Field(default_factory=list)
    total: int = 0
    limit: int = 100
    offset: int = 0


class HistoryDetailResponse(BaseModel):
    entry_id: str
    request_id: str
    processed_at: str
    result_json: dict
    image_urls: ImageUrls = Field(default_factory=ImageUrls)


class DeleteHistoryResponse(BaseModel):
    entry_id: str
    deleted: bool = True
