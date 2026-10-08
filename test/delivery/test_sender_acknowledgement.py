"""Execute actual adapter functions without registering production jobs."""
import ast
import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from nonebot.adapters.onebot.v11 import Message
from src.services.delivery.followups import FollowupDelivery
from src.services.delivery.periodic import PeriodicDelivery
from src.services.persistence.effects import EffectUnavailable, EffectWriter
from src.services.persistence.effects.source import SourceEffectWriter
from test.autonomy.test_pending_atomic import isolated_redis


def periodic_fixture(storage, dedup, send, client):
    async def schedule(_kind, _target, callback, **_kwargs):
        return await callback()

    service = PeriodicDelivery(client, storage, dedup, schedule=schedule)
    return service, SimpleNamespace(self_id="99", send_group_msg=send)


def followup_fixture(relationship, dedup, send, client):
    """Exercise actual followup bookkeeping with isolated durable sources."""
    from src.models.schemas import RelationshipMemory
    from src.services.persistence.followups import mutate

    service = FollowupDelivery(client, dedup)
    by_id = {item.memory_id: item for item in relationship.get_due_followups.return_value}

    for memory_id, item in by_id.items():
        memory = RelationshipMemory(memory_id=memory_id, user_id=item.user_id, memory_type="promise",
                                    content=item.content, due_at=datetime.now() - timedelta(seconds=1))
        assert mutate(client, "create", item.user_id, memory_id, payload=memory.model_dump_json(),
                      revision="revision", due=memory.due_at.timestamp())

    async def schedule(_kind, user_id, callback, *, category):
        send.category = category
        return await callback()

    service.schedule = schedule
    bot = SimpleNamespace(self_id="99", send_private_msg=send)
    return service, bot


def load_function(relative_path, name, namespace):
    root = Path(__file__).resolve().parents[2]
    tree = ast.parse((root / relative_path).read_text(encoding="utf-8"))
    node = next(item for item in tree.body if isinstance(item, ast.AsyncFunctionDef) and item.name == name)
    node.decorator_list = []
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), node], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), relative_path, "exec"), namespace)
    return namespace[name]


@pytest.mark.asyncio
@pytest.mark.parametrize("delivered", [False, True])
async def test_reminder_adapter_delegates_persistent_version_and_ack(delivered):
    service = SimpleNamespace(deliver=AsyncMock(return_value=delivered))
    snapshot = SimpleNamespace(revision="v1", intent={"bot_id": "99"})
    runtime = SimpleNamespace(source=SimpleNamespace(load=Mock(return_value=snapshot), redis=object()),
                              wait_seconds=120)
    bot, logger = Mock(), Mock()
    function = load_function("src/plugins/chat/reminders.py", "send_group_reminder", {
        "asyncio": asyncio, "get_bot": Mock(return_value=bot), "logger": logger,
        "_runtime": AsyncMock(return_value=runtime), "ReminderDelivery": Mock(return_value=service),
    })
    await function("fixture", "v1", 1234)
    service.deliver.assert_awaited_once_with(bot, "fixture", "v1", valid_until_ms=1234)
    assert logger.warning.call_count == int(not delivered)


@pytest.mark.asyncio
async def test_startup_restore_failure_is_reported_without_retry():
    runtime = SimpleNamespace(restore=AsyncMock(side_effect=ConnectionError))
    logger = Mock()
    function = load_function("src/plugins/chat/reminders.py", "restore_persisted_reminders", {
        "_runtime": AsyncMock(return_value=runtime), "logger": logger,
    })
    await function()
    runtime.restore.assert_awaited_once()
    logger.exception.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("delivered", [False, True])
async def test_periodic_news_only_recorded_after_send(delivered, isolated_redis):
    dedup = Mock(check=Mock(return_value=SimpleNamespace(allowed=True)))
    storage = Mock()
    service, bot = periodic_fixture(storage, dedup, AsyncMock(return_value=delivered), isolated_redis)
    assert await service.deliver(bot, 1, "fixture", intent="daily_digest", task="test",
                                 period=datetime.now(timezone.utc).date(), timezone=timezone.utc) is delivered
    assert isolated_redis.llen("outbound:ledger:group:1") == int(delivered)
    assert isolated_redis.llen("all_memory") == int(delivered)
    dedup.record.assert_not_called()
    storage.append_global_record.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["dedup", "completion"])
async def test_followup_bookkeeping_failure_does_not_skip_other_write(failure, isolated_redis, monkeypatch):
    memories = [SimpleNamespace(user_id=7, memory_id=str(i), content=f"fixture {i}") for i in range(2)]
    relationship = Mock(get_due_followups=Mock(return_value=memories))
    dedup = Mock(check=Mock(return_value=SimpleNamespace(allowed=True)))
    target_class, method = ((EffectWriter, "record_outbound") if failure == "dedup"
                            else (SourceEffectWriter, "complete_effect"))
    original = getattr(target_class, method)
    calls = 0

    def fail_once(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise EffectUnavailable("synthetic write outcome unknown")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(target_class, method, fail_once)
    send = AsyncMock(return_value=True)
    service, bot = followup_fixture(relationship, dedup, send, isolated_redis)
    function = load_function("src/plugins/relationship_followups.py", "deliver_due_followups", {
        "settings": SimpleNamespace(proactive_enabled=True), "asyncio": asyncio,
        "relationship": relationship, "dedup": dedup, "get_bot": lambda: bot,
        "storage": SimpleNamespace(redis=object()), "FollowupDelivery": lambda *_: service,
        "Message": Message, "logger": Mock(), "send_to_private": send,
    })
    await function()
    assert send.await_count == 2
    assert calls == 2
    statuses = [json.loads(isolated_redis.hget("relationship:7", str(i)))["status"] for i in range(2)]
    assert statuses == (["active", "done"] if failure == "completion" else ["done", "done"])
    assert isolated_redis.llen("outbound:ledger:private:7") == (1 if failure == "dedup" else 2)
    dedup.record.assert_not_called()
    relationship.mark_done.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["dedup", "history"])
async def test_periodic_news_bookkeeping_failure_preserves_delivery(failure, isolated_redis, monkeypatch):
    dedup = Mock(check=Mock(return_value=SimpleNamespace(allowed=True)))
    storage = Mock()
    method = "record_outbound" if failure == "dedup" else "append_global_record"
    monkeypatch.setattr(EffectWriter, method, Mock(side_effect=EffectUnavailable))
    send = AsyncMock(return_value=True)
    service, bot = periodic_fixture(storage, dedup, send, isolated_redis)
    assert await service.deliver(bot, 1, "fixture", intent="daily_digest", task="test",
                                 period=datetime.now(timezone.utc).date(), timezone=timezone.utc) is True
    send.assert_awaited_once()
    assert isolated_redis.llen("outbound:ledger:group:1") == int(failure != "dedup")
    assert isolated_redis.llen("all_memory") == int(failure != "history")
    dedup.record.assert_not_called()
    storage.append_global_record.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("delivered", [False, True])
async def test_relationship_followup_only_completed_after_acknowledgement(delivered, isolated_redis):
    memory = SimpleNamespace(user_id=7, memory_id="promise", content="fixture")
    relationship = Mock(get_due_followups=Mock(return_value=[memory]))
    dedup = Mock(check=Mock(return_value=SimpleNamespace(allowed=True)))
    send = AsyncMock(return_value=delivered)
    service, bot = followup_fixture(relationship, dedup, send, isolated_redis)
    function = load_function("src/plugins/relationship_followups.py", "deliver_due_followups", {
        "settings": SimpleNamespace(proactive_enabled=True), "asyncio": asyncio,
        "relationship": relationship, "dedup": dedup, "get_bot": lambda: bot,
        "storage": SimpleNamespace(redis=object()), "FollowupDelivery": lambda *_: service,
        "Message": Message, "logger": Mock(), "send_to_private": send,
    })
    await function()
    assert send.category == "reminder"
    status = json.loads(isolated_redis.hget("relationship:7", "promise"))["status"]
    assert status == ("done" if delivered else "active")
    assert isolated_redis.llen("outbound:ledger:private:7") == int(delivered)
    relationship.mark_done.assert_not_called()
    dedup.record.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["fingerprints", "fetch", "unacknowledged"])
async def test_manual_digest_distinguishes_delivery_from_fingerprint_failure(failure):
    storage = Mock()
    if failure == "fingerprints":
        storage.record_sent_news.side_effect = OSError("write outcome unknown")
    fetch = AsyncMock(return_value=("date", ["section"]))
    if failure == "fetch":
        fetch.side_effect = OSError("fetch failed")
    send = AsyncMock(return_value=failure != "unacknowledged")
    notice, logger = AsyncMock(), Mock()
    namespace = {
        "asyncio": asyncio, "_storage": storage, "logger": logger,
        "_fetch_digest_sections": fetch, "_render_digest": Mock(return_value="digest"),
        "_digest_fingerprints": Mock(return_value=["fingerprint"]),
        "send_to_event": send, "send_notice": notice,
    }
    entry = load_function("src/plugins/scheduler.py", "handle_daily_news", namespace)
    await entry(object(), object())
    assert send.await_count == int(failure != "fetch")
    assert storage.record_sent_news.call_count == int(failure == "fingerprints")
    assert logger.exception.call_count == int(failure == "fetch")
    if failure == "fingerprints":
        logger.warning.assert_called_once()
    keys = [call.kwargs["notice_key"] for call in notice.await_args_list]
    assert keys == (["news.loading", "news.unavailable"] if failure == "fetch" else ["news.loading"])
