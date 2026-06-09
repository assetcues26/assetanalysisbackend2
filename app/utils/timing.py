"""Timing utilities."""

import time
from contextlib import contextmanager
from typing import Generator


@contextmanager
def timer() -> Generator[list[float], None, None]:
    start = time.perf_counter()
    elapsed: list[float] = [0.0]
    try:
        yield elapsed
    finally:
        elapsed[0] = (time.perf_counter() - start) * 1000
