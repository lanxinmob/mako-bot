"""Contracts across repositories that share one in-memory backend."""
from datetime import datetime

from src.models.schemas import ChatRecord
from src.services.persistence import StorageService
from src.services.persistence.backends.memory import MemoryStorage


def test_explicit_backend_injection_does_not_read_global_configuration(monkeypatch):
    from src.services.persistence.backends import redis as backend_module
    from types import SimpleNamespace

    def forbidden():
        raise AssertionError("explicit injection must not read global configuration")

    monkeypatch.setattr(backend_module, "get_settings", forbidden)
    service = object.__new__(StorageService)
    service.redis = None
    service.settings = SimpleNamespace(max_history_turns=2)
    service.backend.memory = MemoryStorage()
    service.save_history("fixture", [{"role": "user", "content": "injected"}])
    assert service.get_history("fixture")[0]["content"] == "injected"


def test_global_record_is_readable_across_facades_with_shared_backend():
    first = object.__new__(StorageService)
    first.redis = None
    first.backend.memory = MemoryStorage()
    second = object.__new__(StorageService)
    second._backend = first.backend
    record = ChatRecord(
        user_id=42, nickname="fixture", role="user", content="shared record",
        time=datetime.now(), message_type="private",
    )
    first.append_global_record(record)
    assert second.list_global_records()[0].content == "shared record"
    assert second.get_recent_global_records()[0].user_id == 42
    second.save_history("private_42", [{"role": "user", "content": "hello"}])
    assert first.get_history("private_42")[0]["content"] == "hello"


def test_image_references_round_trip_without_image_binary_or_empty_field():
    from types import SimpleNamespace
    import json

    storage = object.__new__(StorageService)
    storage.redis = None
    storage.settings = SimpleNamespace(redis_required=False, global_memory_max_records=1000)
    storage.backend.memory = MemoryStorage()
    legacy = ChatRecord(role="user", content="fixture")
    storage.append_global_record(legacy)
    assert "image_urls" not in json.loads(storage.backend.memory.all_memory[0])
    record = ChatRecord(role="user", content="图片", image_urls=["https://example.com/a"])
    storage.append_global_record(record)
    assert list(storage.iter_global_image_urls()) == record.image_urls
    assert storage.list_global_records()[0].image_urls == record.image_urls
