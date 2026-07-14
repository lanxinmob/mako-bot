"""Unauthenticated liveness and readiness probes with no sensitive payloads."""

from __future__ import annotations

import asyncio

from fastapi.responses import JSONResponse
from nonebot import get_driver
from nonebot.log import logger

from src.core.config import get_settings
from src.services.llm import has_deepseek, has_openai
from src.services.redis import get_redis


driver = get_driver()


def readiness_snapshot() -> tuple[bool, dict]:
    settings = get_settings()
    redis_client = get_redis()
    redis_ok = False
    if redis_client is not None:
        try:
            redis_ok = bool(redis_client.ping())
        except Exception:
            redis_ok = False
    llm_ok = has_deepseek() or has_openai()
    checks = {
        "redis": "ok" if redis_ok else "unavailable",
        "llm": "configured" if llm_ok else "not_configured",
    }
    ready = (redis_ok or not settings.redis_required) and (
        llm_ok or not settings.llm_required
    )
    return ready, checks


@driver.on_startup
async def mount_health_routes() -> None:
    app = getattr(driver, "server_app", None)
    if app is None:
        logger.warning("FastAPI server_app is unavailable; health routes were not mounted.")
        return

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @app.get("/readyz", include_in_schema=False)
    async def readyz() -> JSONResponse:
        ready, checks = await asyncio.to_thread(readiness_snapshot)
        return JSONResponse(
            {"status": "ready" if ready else "not_ready", "checks": checks},
            status_code=200 if ready else 503,
        )
