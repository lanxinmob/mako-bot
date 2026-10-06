from __future__ import annotations

import time
from threading import RLock
from typing import Optional

import redis
from nonebot.log import logger

from src.core.config import get_settings


_client: Optional[redis.Redis] = None
_last_failure_at = 0.0
_last_health_at = 0.0
_connection_lock = RLock()


def reset_redis_connection() -> None:
    """Forget the cached client so the next access performs a fresh health check."""

    global _client, _last_failure_at, _last_health_at
    with _connection_lock:
        if _client is not None:
            try:
                _client.close()
            except Exception:
                pass
        _client = None
        _last_failure_at = 0.0
        _last_health_at = 0.0


def get_redis() -> Optional[redis.Redis]:
    """Return a healthy Redis client and periodically retry startup failures."""

    global _client, _last_failure_at, _last_health_at
    settings = get_settings()
    now = time.monotonic()
    with _connection_lock:
        if _client is not None:
            if now - _last_health_at < max(1.0, settings.redis_health_check_seconds):
                return _client
            try:
                _client.ping()
                _last_health_at = now
                return _client
            except Exception as exc:
                logger.warning(f"Redis connection became unhealthy; reconnecting: {exc}")
                try:
                    _client.close()
                except Exception:
                    pass
                _client = None
                _last_health_at = 0.0

        if _last_failure_at and now - _last_failure_at < max(1.0, settings.redis_retry_seconds):
            return None
        try:
            client = redis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=3.0,
                socket_timeout=5.0,
                health_check_interval=30,
                retry_on_timeout=True,
                protocol=2,
            )
            client.ping()
            _client = client
            _last_failure_at = 0.0
            _last_health_at = now
            return _client
        except Exception as exc:
            _last_failure_at = now
            logger.warning(f"Redis unavailable, falling back to in-memory mode: {exc}")
            return None


from .memory import memory_store


class StorageBackend:
    def __init__(self, settings=None, redis_provider=None, *, initialize=True):
        self._settings = settings
        if initialize and self._settings is None:
            self._settings = get_settings()
        self.memory = memory_store
        self._provider = redis_provider if redis_provider is not None else get_redis
        self._redis = self._provider() if initialize else None
        self._override = False

    @property
    def settings(self):
        if self._settings is None:
            self._settings = get_settings()
        return self._settings

    @settings.setter
    def settings(self, value):
        self._settings = value

    @property
    def redis(self):
        if not self._override:
            self._redis = self._provider()
        return self._redis

    @redis.setter
    def redis(self, value):
        self._redis = value
        self._override = True
