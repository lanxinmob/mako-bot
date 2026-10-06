"""Private Owner access and read-only bounded generation evidence queries."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.services.persistence.generation.review import list_generations
from test.autonomy.owner_loader import load_owner
from test.autonomy.test_pending_atomic import isolated_redis
from test.chat.generation.test_store import attempt


@pytest.mark.asyncio
@pytest.mark.parametrize("state,label", [
    ("calling", "结果未确认"), ("unknown", "结果未知"),
    ("completed", "待补记"), ("invalid", "需人工核对"), ("missing", "没有记录"),
])
async def test_owner_query_preserves_all_evidence_and_hides_tokens(attempt, monkeypatch, state, label):
    client, store, spec = attempt
    token = store.start(spec)
    if state == "unknown":
        store.mark_unknown(spec, token)
    elif state == "completed":
        store.complete(spec, token, .05)
    elif state == "invalid":
        client.set(store.key(spec.attempt_id), "PRIVATE MALFORMED DATA")
    elif state == "missing":
        client.delete(store.key(spec.attempt_id))
    owner = load_owner()
    ctx = SimpleNamespace(settings=SimpleNamespace(autonomy_owner_id=99),
                          repository=SimpleNamespace(redis_client=client),
                          policy=SimpleNamespace(is_enabled=lambda: False))
    event = Mock(spec=owner.PrivateMessageEvent, user_id=99)
    event.get_plaintext.return_value = f"生成状态 {spec.attempt_id}"
    feedback = AsyncMock()
    monkeypatch.setitem(owner.process_delivery_command.__globals__, "send_to_event", feedback)
    before = {key: client.dump(key) for key in client.scan_iter()}
    assert await owner.autonomy_rule(ctx, event)
    bot = Mock()
    assert await owner.process_owner_private(ctx, bot, Mock(), event, event.get_plaintext())
    message = feedback.await_args.args[2]
    assert label in message
    assert "不触发" in message or "未触发" in message
    assert token not in message and "PRIVATE" not in message and spec.input_digest not in message
    assert {key: client.dump(key) for key in client.scan_iter()} == before
    assert not bot.mock_calls


@pytest.mark.asyncio
@pytest.mark.parametrize("private,owner_id", [(False, 99), (True, 100)])
async def test_non_owner_or_group_cannot_query(attempt, monkeypatch, private, owner_id):
    client, _, spec = attempt
    owner = load_owner()
    ctx = SimpleNamespace(settings=SimpleNamespace(autonomy_owner_id=99),
                          repository=SimpleNamespace(redis_client=client))
    event = Mock(spec=owner.PrivateMessageEvent, user_id=owner_id) if private else SimpleNamespace(user_id=owner_id)
    feedback = AsyncMock()
    monkeypatch.setitem(owner.process_delivery_command.__globals__, "send_to_event", feedback)
    assert not await owner.process_delivery_command(ctx, Mock(), event, f"生成状态 {spec.attempt_id}")
    feedback.assert_not_awaited()


def test_generation_listing_retains_oversized_batch_and_marks_bad_record():
    ids = [f"{index:064x}" for index in range(12)]
    keys = ["mako:generation:v1:" + value for value in ids]
    client = SimpleNamespace(scan=Mock(return_value=(0, list(reversed(keys)))),
                             get=Mock(return_value="invalid"))
    first = list_generations(client)
    assert len(first.entries) == 10 and first.next_cursor == "0:10"
    assert all(entry.state == "invalid" for entry in first.entries)
    last = list_generations(client, first.next_cursor)
    assert len(last.entries) == 2 and last.next_cursor is None
    assert [entry.attempt_id for entry in first.entries + last.entries] == ids


@pytest.mark.asyncio
async def test_actual_generation_list_command(attempt, monkeypatch):
    client, store, spec = attempt
    store.mark_unknown(spec, store.start(spec))
    owner = load_owner()
    ctx = SimpleNamespace(settings=SimpleNamespace(autonomy_owner_id=99),
                          repository=SimpleNamespace(redis_client=client))
    event = Mock(spec=owner.PrivateMessageEvent, user_id=99)
    feedback = AsyncMock()
    monkeypatch.setitem(owner.process_delivery_command.__globals__, "send_to_event", feedback)
    first = client.dump(store.key(spec.attempt_id))
    assert await owner.process_delivery_command(ctx, Mock(), event, "生成列表")
    assert spec.attempt_id in feedback.await_args.args[2]
    assert "结果未知" in feedback.await_args.args[2]
    assert client.dump(store.key(spec.attempt_id)) == first
