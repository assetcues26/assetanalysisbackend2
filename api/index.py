"""Vercel serverless entrypoint for FastAPI."""

from app.main import app

__all__ = ["app"]
