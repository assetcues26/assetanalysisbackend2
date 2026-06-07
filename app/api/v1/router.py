"""API v1 router."""

from fastapi import APIRouter

from app.api.v1 import assets, audit

router = APIRouter(prefix="/v1")
router.include_router(assets.router, tags=["assets"])

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(audit.router, tags=["audit"])
