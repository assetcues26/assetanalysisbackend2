"""FastAPI application entry point."""

import structlog
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app

from app.api.v1.router import api_router, router as v1_router
from app.api.v6.router import router as v6_router
from app.config import get_settings
from app.middleware.multipart import MultipartSizeMiddleware
from app.utils.network import get_all_lan_ipv4, get_lan_ipv4

structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ]
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Asset Analysis API",
        description="Analyze physical assets from a single photo using Gemini AI",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # After CORS so the patched Request reaches route handlers (Starlette default part cap is 1MB).
    app.add_middleware(MultipartSizeMiddleware)

    settings = get_settings()

    app.include_router(v1_router)
    if settings.v6_demo_enabled:
        app.include_router(v6_router)
    app.include_router(api_router)
    app.mount("/metrics", make_asgi_app())

    @app.get("/")
    async def root():
        lan_ip = get_lan_ipv4()
        all_ips = get_all_lan_ipv4()
        port = 8000
        lan_base = f"http://{lan_ip}:{port}" if lan_ip else None
        return {
            "service": "Multi-Image Asset Analysis API",
            "docs": "/docs",
            "health": "/v1/health",
            "local": f"http://127.0.0.1:{port}",
            "lan_ipv4": lan_ip,
            "lan_ipv4_all": all_ips,
            "lan_base_url": lan_base,
            "lan_docs": f"{lan_base}/docs" if lan_base else None,
            "lan_analyze_collage": f"{lan_base}/v1/assets/analyze/collage" if lan_base else None,
            "lan_analyze_multi": f"{lan_base}/v1/assets/analyze/multi" if lan_base else None,
            "start_command": "python serve.py",
            "ui_api_base_example": lan_base or f"http://<your-pc-ip>:{port}",
        }

    return app


app = create_app()
