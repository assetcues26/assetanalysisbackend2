"""Raise Starlette's default 1MB multipart part limit for image uploads."""

from collections.abc import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.config import get_settings


class MultipartSizeMiddleware(BaseHTTPMiddleware):
    """Starlette caps each multipart part at 1MB by default; base64 needs a higher cap."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        max_part_size = get_settings().max_multipart_part_bytes
        original_form = request.form

        def form_with_larger_parts(**kwargs):
            kwargs.setdefault("max_part_size", max_part_size)
            return original_form(**kwargs)

        request.form = form_with_larger_parts  # type: ignore[method-assign]
        return await call_next(request)
