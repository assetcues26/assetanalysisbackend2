"""Tests for SaaS image compression."""

from PIL import Image

from app.utils.saas_image_compress import (
    TAGGING_AI_MAX_FILE_BYTES,
    compress_image_bytes_for_tagging_ai,
)


def _large_jpeg_bytes(width: int = 6000, height: int = 4500) -> bytes:
    img = Image.new("RGB", (width, height), color=(120, 80, 200))
    from io import BytesIO

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def test_compress_large_image_under_cap():
    raw = _large_jpeg_bytes()
    out = compress_image_bytes_for_tagging_ai(raw)
    assert len(out) <= TAGGING_AI_MAX_FILE_BYTES
    assert out[:3] == b"\xff\xd8\xff"
    if len(raw) > TAGGING_AI_MAX_FILE_BYTES:
        assert len(out) < len(raw)


def test_small_image_left_unchanged_when_under_cap():
    img = Image.new("RGB", (200, 200), color=(10, 20, 30))
    from io import BytesIO

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=80)
    raw = buf.getvalue()

    out = compress_image_bytes_for_tagging_ai(raw)
    assert len(out) <= TAGGING_AI_MAX_FILE_BYTES
