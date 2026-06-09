"""Vercel entrypoint — re-exports the FastAPI app for zero-config detection."""

from app.main import app

__all__ = ["app"]
