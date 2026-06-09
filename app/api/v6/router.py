"""V6 demo router mount."""

from fastapi import APIRouter

from app.api.v6 import demo

router = APIRouter(prefix="/v6")
router.include_router(demo.router, tags=["V6 Demo"])
