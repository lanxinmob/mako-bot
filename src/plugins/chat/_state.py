"""Shared singletons, mutable globals, and constants for the chat plugin.

All sub-modules import from here instead of creating their own copies.
Nginx-inspired: one well-known location for shared mutable state.
"""

from __future__ import annotations

import time
from datetime import timedelta, timezone
from typing import Any, Dict, List

from openai import AsyncOpenAI

from src.core.config import get_settings
from src.services.redis import get_redis
from src.services.storage import StorageService

# ── Singletons (created once, shared everywhere) ──────────────────────────
_settings = get_settings()
client = AsyncOpenAI(
    api_key=_settings.deepseek_api_key,
    base_url=_settings.deepseek_base_url,
)
redis_client = get_redis()
audit_storage = StorageService()

# ── Mutable module-level state ───────────────────────────────────────────
# (N.B. no asyncio.Lock — acceptable for low-concurrency single-bot deployment)
user_reminders: Dict[str, List[Dict[str, Any]]] = {}
chat_histories: Dict[str, List[dict]] = {}
_image_rate_limit: Dict[int, float] = {}

# ── Constants ─────────────────────────────────────────────────────────────
MAX_HISTORY_TURNS: int = 50
MAX_IMAGES_TO_DESCRIBE: int = 3

MAX_SEARCH_RESULTS: int = 5
MAX_SEARCH_CONTEXT_RESULTS: int = 3
MAX_SEARCH_QUERIES: int = 3
MAX_SEARCH_SNIPPET_CHARS: int = 240
MAX_URL_CONTEXT_CHARS: int = 3000

LOCAL_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")
