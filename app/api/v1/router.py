"""API v1 router."""

from fastapi import APIRouter

from app.api.v1 import assets, audit, demo, history, sessions

router = APIRouter(prefix="/v1")
router.include_router(assets.router, tags=["assets"])
router.include_router(history.router, tags=["history"])
router.include_router(sessions.router, tags=["sessions"])
router.include_router(demo.router, tags=["demo"])

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(audit.router, tags=["audit"])
