"""Demo maintenance API models."""

from pydantic import BaseModel, Field


class ClearDemoDataResponse(BaseModel):
    cleared: bool = True
    analyses_deleted: int = 0
    sessions_deleted: int = 0
    storage_objects_removed: int = 0
    message: str = Field(default="Demo data cleared. Tables and schema unchanged.")
