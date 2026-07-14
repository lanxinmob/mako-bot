from __future__ import annotations

import asyncio
import hmac
from pathlib import Path
from typing import Optional

from fastapi import Header, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from nonebot import get_driver
from nonebot.log import logger

from src.core.config import get_settings
from src.web.dashboard.service import DashboardService


driver = get_driver()
settings = get_settings()

STATIC_DIR = Path(__file__).resolve().parents[2] / "web" / "dashboard" / "static"
ASSETS_DIR = STATIC_DIR / "assets"
INDEX_FILE = STATIC_DIR / "index.html"


def _require_dashboard_token(
    authorization: Optional[str] = Header(default=None),
    x_dashboard_token: Optional[str] = Header(default=None),
) -> None:
    expected = settings.dashboard_token
    if not expected:
        raise HTTPException(status_code=503, detail="DASHBOARD_TOKEN is not configured")

    supplied = x_dashboard_token
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid dashboard token")


SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self'; "
        "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


@driver.on_startup
async def mount_dashboard_routes() -> None:
    app = getattr(driver, "server_app", None)
    if app is None:
        logger.warning("FastAPI server_app is not available; dashboard routes were not mounted.")
        return
    if not INDEX_FILE.exists():
        logger.warning(f"Dashboard static index not found: {INDEX_FILE}")
        return

    if ASSETS_DIR.exists():
        app.mount(
            "/mako/dashboard/assets",
            StaticFiles(directory=str(ASSETS_DIR)),
            name="mako_dashboard_assets",
        )

    @app.get("/mako/dashboard")
    @app.get("/mako/dashboard/")
    async def dashboard_page() -> FileResponse:
        return FileResponse(
            str(INDEX_FILE),
            media_type="text/html; charset=utf-8",
            headers=SECURITY_HEADERS,
        )

    @app.get("/mako/dashboard/api/summary")
    async def dashboard_summary(
        limit: int = Query(default=100, ge=1, le=200),
        authorization: Optional[str] = Header(default=None),
        x_dashboard_token: Optional[str] = Header(default=None),
    ) -> JSONResponse:
        _require_dashboard_token(authorization, x_dashboard_token)
        service = DashboardService()
        payload = await asyncio.to_thread(service.get_frontend_summary, limit=limit)
        return JSONResponse(payload, headers=SECURITY_HEADERS)


logger.success("茉子 Dashboard 插件已加载，入口 /mako/dashboard")
