"""Compress SaaS asset photos for Supabase storage and Tagging AI (Vercel ~4.5MB limit)."""

from __future__ import annotations

import io

from PIL import Image, ImageOps

# Match frontend MOBILE_MAX_FILE_KB (500KB per file).
TAGGING_AI_MAX_FILE_BYTES = 500_000
TAGGING_AI_MAX_EDGE_PX = 1600


def compress_image_bytes_for_tagging_ai(
    data: bytes,
    *,
    max_bytes: int = TAGGING_AI_MAX_FILE_BYTES,
    max_edge: int = TAGGING_AI_MAX_EDGE_PX,
) -> bytes:
    """Return JPEG bytes ≤ *max_bytes* for Tagging AI / SaaS storage."""
    if not data:
        return data

    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
    except Exception as exc:
        raise ValueError(f"Invalid or corrupted image: {exc}") from exc

    edge = max_edge
    quality = 85
    for _ in range(8):
        working = img
        w, h = working.size
        longest = max(w, h)
        if longest > edge:
            scale = edge / longest
            working = working.resize(
                (max(1, int(w * scale)), max(1, int(h * scale))),
                Image.Resampling.LANCZOS,
            )
        buf = io.BytesIO()
        working.save(buf, format="JPEG", quality=quality, optimize=True)
        out = buf.getvalue()
        if len(out) <= max_bytes:
            return out
        edge = max(480, int(edge * 0.75))
        quality = max(45, quality - 10)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=45, optimize=True)
    return buf.getvalue()
