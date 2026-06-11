"""Capture session API models."""

from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):
    processing_mode: str = Field(default="direct", pattern="^(collage|direct)$")
    market_region: str | None = Field(
        default=None,
        description="Omit to use server default (MARKET_REGION env)",
    )


class SessionImageItem(BaseModel):
    id: str
    sort_order: int
    preview_url: str | None = None
    source: str
    file_name: str | None = None
    mime_type: str = "image/jpeg"
    byte_size: int | None = None


class CreateSessionResponse(BaseModel):
    session_token: str
    status: str
    processing_mode: str
    market_region: str = "IN"
    image_count: int = 0
    expires_at: str
    images: list[SessionImageItem] = Field(default_factory=list)


class SessionDetailResponse(BaseModel):
    session_token: str
    status: str
    processing_mode: str
    market_region: str = "IN"
    image_count: int
    max_images: int
    total_bytes: int = 0
    entry_id: str | None = None
    expires_at: str
    images: list[SessionImageItem] = Field(default_factory=list)


class SessionImagesResponse(BaseModel):
    session_token: str
    status: str
    image_count: int
    images: list[SessionImageItem] = Field(default_factory=list)


class AnalyzeSessionResponse(BaseModel):
    session_token: str
    status: str
    entry_id: str | None = None
    saved_to_db: bool = False


class CancelSessionRequest(BaseModel):
    clear_images: bool = False
