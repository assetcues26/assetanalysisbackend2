"""Build one labeled collage image from multiple asset photos (Pillow only)."""

import math

from PIL import Image, ImageDraw, ImageFont

_BG = (255, 255, 255)
_LABEL_BG = (17, 24, 39)
_LABEL_FG = (255, 255, 255)
_PADDING = 14
_LABEL_H = 30


def _load_font(size: int) -> ImageFont.ImageFont:
    for name in ("arial.ttf", "DejaVuSans.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def build_collage(
    images: list[Image.Image],
    cell_px: int = 900,
    labels: list[str] | None = None,
) -> Image.Image:
    """Arrange images into a labeled grid on a single canvas."""
    if not images:
        raise ValueError("build_collage requires at least one image")

    n = len(images)
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)
    cell_w = cell_h = cell_px

    canvas_w = cols * cell_w + (cols + 1) * _PADDING
    canvas_h = rows * (cell_h + _LABEL_H) + (rows + 1) * _PADDING
    canvas = Image.new("RGB", (canvas_w, canvas_h), _BG)
    draw = ImageDraw.Draw(canvas)
    font = _load_font(20)

    for idx, img in enumerate(images):
        row, col = divmod(idx, cols)
        x = _PADDING + col * (cell_w + _PADDING)
        y = _PADDING + row * (cell_h + _LABEL_H + _PADDING)

        label = labels[idx] if labels and idx < len(labels) else f"Image {idx + 1}"
        draw.rectangle([x, y, x + cell_w, y + _LABEL_H], fill=_LABEL_BG)
        draw.text((x + 8, y + 6), label, fill=_LABEL_FG, font=font)

        thumb = img.convert("RGB").copy()
        thumb.thumbnail((cell_w, cell_h), Image.Resampling.LANCZOS)
        ox = x + (cell_w - thumb.width) // 2
        oy = y + _LABEL_H + (cell_h - thumb.height) // 2
        canvas.paste(thumb, (ox, oy))

    return canvas
