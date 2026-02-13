from __future__ import annotations

from functools import lru_cache
from typing import Optional

import redis
from nonebot.log import logger

from src.core.config import get_settings


@lru_cache
def get_redis() -> Optional[redis.Redis]:
    settings = get_settings()
    try:
        client = redis.from_url(settings.redis_url, decode_responses=True)
        client.ping()
        return client
    except Exception as exc:
        logger.warning(f"Redis unavailable, falling back to in-memory mode: {exc}")
        return None
