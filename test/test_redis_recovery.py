from __future__ import annotations

from types import SimpleNamespace

from src.services import redis as redis_service
from src.services import storage as storage_module
from src.services.storage import StorageService
from src.services.vector_store import VectorStore


class FakeRedis:
    def __init__(self, *, healthy: bool = True) -> None:
        self.healthy = healthy
        self.closed = False

    def ping(self) -> bool:
        if not self.healthy:
            raise ConnectionError("down")
        return True

    def close(self) -> None:
        self.closed = True


def test_storage_refreshes_the_shared_connection(monkeypatch) -> None:
    first = FakeRedis()
    second = FakeRedis()
    values = iter([first, second])
    monkeypatch.setattr(storage_module, "get_redis", lambda: next(values))

    storage = StorageService()
    assert storage.redis is second


def test_vector_store_refreshes_the_shared_connection(monkeypatch) -> None:
    import src.services.vector_store as vector_module

    first = FakeRedis()
    second = FakeRedis()
    values = iter([first, second])
    monkeypatch.setattr(vector_module, "get_redis", lambda: next(values))

    store = VectorStore()
    assert store.redis is second


def test_unhealthy_cached_client_is_replaced(monkeypatch) -> None:
    unhealthy = FakeRedis(healthy=False)
    replacement = FakeRedis()
    redis_service._client = unhealthy
    redis_service._last_health_at = 0.0
    redis_service._last_failure_at = 0.0
    monkeypatch.setattr(
        redis_service,
        "get_settings",
        lambda: SimpleNamespace(
            redis_url="redis://example/0",
            redis_retry_seconds=1.0,
            redis_health_check_seconds=1.0,
        ),
    )
    monkeypatch.setattr(redis_service.redis, "from_url", lambda *_args, **_kwargs: replacement)

    assert redis_service.get_redis() is replacement
    assert unhealthy.closed is True
    redis_service.reset_redis_connection()
