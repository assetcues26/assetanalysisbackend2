"""Multipart image upload parsing (file uploads only)."""

import io
from typing import BinaryIO

from fastapi import HTTPException, UploadFile, status

from app.config import Settings

UploadTuple = tuple[BinaryIO, str, bytes]


def validate_mime(content_type: str | None, settings: Settings) -> str:
    mime = (content_type or "").split(";")[0].strip().lower()
    if mime == "image/jpg":
        mime = "image/jpeg"
    if mime not in settings.allowed_mime_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported image type: {mime or 'unknown'}. "
                f"Allowed: {', '.join(settings.allowed_mime_types)}"
            ),
        )
    return mime


def sniff_image_mime(raw: bytes) -> str | None:
    if len(raw) >= 3 and raw[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if len(raw) >= 8 and raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    return None


def _finalize_image_bytes(
    raw: bytes,
    filename: str,
    content_type: str | None,
    settings: Settings,
) -> UploadTuple:
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Image '{filename}' is empty",
        )
    if len(raw) > settings.max_image_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Image '{filename}' exceeds {settings.max_image_size_mb}MB limit",
        )

    mime = (content_type or "").split(";")[0].strip().lower() or None
    if mime == "image/jpg":
        mime = "image/jpeg"
    if not mime:
        mime = sniff_image_mime(raw)
    if not mime:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not detect image type for '{filename}'; use JPEG, PNG, or WebP",
        )
    validate_mime(mime, settings)
    return io.BytesIO(raw), filename, raw


async def resolve_uploaded_images(
    images: list[UploadFile],
    settings: Settings,
) -> list[UploadTuple]:
    """Validate and read 1..max_images uploaded image files."""
    real = [img for img in (images or []) if img is not None and (img.filename or img.content_type)]
    if len(real) < settings.min_images:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"At least {settings.min_images} image file is required",
        )
    limit = settings.upload_image_limit
    if len(real) > limit:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"At most {limit} images allowed (got {len(real)})",
        )

    parsed: list[UploadTuple] = []
    for idx, upload in enumerate(real):
        raw = await upload.read()
        parsed.append(
            _finalize_image_bytes(
                raw,
                upload.filename or f"image_{idx + 1}.jpg",
                upload.content_type,
                settings,
            )
        )
    return parsed


MULTI_FILE_OPENAPI = {
    "requestBody": {
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["images"],
                    "properties": {
                        "images": {
                            "type": "array",
                            "items": {"type": "string", "format": "binary"},
                            "description": (
                                "1-10 photos of the SAME asset from different angles "
                                "(JPEG, PNG, or WebP). In Swagger, click 'Add item' per photo."
                            ),
                        },
                        "locale": {
                            "type": "string",
                            "default": "en",
                            "description": "Output language for Gemini response",
                        },
                        "market_region": {
                            "type": "string",
                            "default": "IN",
                            "description": "Market region for valuation: IN | US | GB",
                        },
                    },
                }
            }
        }
    }
}
