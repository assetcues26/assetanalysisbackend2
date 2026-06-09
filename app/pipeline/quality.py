"""Image quality scoring (Pillow/numpy only)."""

import numpy as np
from PIL import Image


def score_blur(pil_image: Image.Image) -> float:
    gray = np.array(pil_image.convert("L"), dtype=np.float64)
    gy, gx = np.gradient(gray)
    return float(np.var(gx) + np.var(gy))


def score_image_quality(blur_score: float) -> float:
    return round(min(1.0, blur_score / 200.0), 3)
