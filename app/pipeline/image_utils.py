"""Shared image encoding helpers."""

import base64
import hashlib
import io

import structlog
from PIL import Image

logger = structlog.get_logger()


def resize_for_gemini(image: Image.Image, max_edge: int) -> Image.Image:
    w, h = image.size
    longest = max(w, h)
    if longest <= max_edge:
        return image
    scale = max_edge / longest
    return image.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)


def image_to_bytes(pil_image: Image.Image, fmt: str = "JPEG", quality: int = 90) -> bytes:
    buf = io.BytesIO()
    pil_image.save(buf, format=fmt, quality=quality)
    return buf.getvalue()


def image_to_base64(pil_image: Image.Image) -> str:
    return base64.b64encode(image_to_bytes(pil_image)).decode("ascii")


def hash_image_set(image_bytes_list: list[bytes]) -> str:
    h = hashlib.sha256()
    for data in sorted(image_bytes_list, key=len):
        h.update(data)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Total-payload budget check
# ---------------------------------------------------------------------------

def fit_images_to_budget(
    images: list[Image.Image],
    max_total_bytes: int,
) -> list[Image.Image]:
    """Progressively resize *images* until their combined JPEG size ≤ *max_total_bytes*.

    Does nothing when the images already fit.  Each round scales every image
    down by 20 % (i.e. 0.8× per dimension).  After 8 rounds the images would
    be ~17 % of their original size, which is more than enough headroom.
    """
    if not images:
        return images

    def _total(imgs: list[Image.Image]) -> int:
        return sum(len(image_to_bytes(img)) for img in imgs)

    total = _total(images)
    if total <= max_total_bytes:
        return images

    logger.info(
        "fit_images_to_budget_triggered",
        original_total_mb=round(total / 1024 / 1024, 2),
        budget_mb=round(max_total_bytes / 1024 / 1024, 2),
        image_count=len(images),
    )

    current = list(images)
    for round_num in range(1, 9):
        current = [
            img.resize(
                (max(1, int(img.width * 0.8)), max(1, int(img.height * 0.8))),
                Image.Resampling.LANCZOS,
            )
            for img in current
        ]
        total = _total(current)
        if total <= max_total_bytes:
            logger.info(
                "fit_images_to_budget_done",
                rounds=round_num,
                final_total_mb=round(total / 1024 / 1024, 2),
            )
            return current

    logger.warning(
        "fit_images_to_budget_exhausted",
        final_total_mb=round(total / 1024 / 1024, 2),
    )
    return current

