"""Shared test fixtures."""

import io

import numpy as np
import pytest
from PIL import Image


def make_test_image(color: tuple[int, int, int], size: tuple[int, int] = (400, 300)) -> bytes:
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def sample_image_bytes() -> bytes:
    return make_test_image((100, 150, 200))


@pytest.fixture
def multi_color_images() -> list[bytes]:
    colors = [
        (200, 50, 50),
        (50, 200, 50),
        (50, 50, 200),
        (200, 200, 50),
    ]
    return [make_test_image(c) for c in colors]
