"""Background delivery reconciliation is separate from autonomy approvals."""
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.services.delivery.state import DeliveryStore, DeliveryUnavailable

from test.autonomy.owner_loader import load_owner
from test.autonomy.test_pending_atomic import isolated_redis
from test.delivery.state.test_store import delivery, expire


@pytest.mark.parametrize("delivered", [False, True])
def test_unknown_only_idempotent_reconciliation_and_late_ack(delivery, delivered):
    client, store, spec = delivery
    claim = store.claim(spec)
    assert not store.reconcile(spec.action_id, delivered=delivered, operator_id="99").ok
    assert store.begin_send(spec, claim.token).ok
    assert not store.reconcile(spec.action_id, delivered=delivered, operator_id="99").ok
    expire(client, store, spec)
    assert store.reconcile(spec.action_id, delivered=delivered, operator_id="99").ok
    first = client.get(store.key(spec.action_id))
    assert store.reconcile(spec.action_id, delivered=delivered, operator_id="100").code == "already_reconciled"
    assert not store.reconcile(spec.action_id, delivered=not delivered, operator_id="99").ok
    assert client.get(store.key(spec.action_id)) == first
    state = json.loads(first)
    assert state["reconciled_by"] == "99" and state["reconciled_at_ms"] > 0
    if delivered:
        assert state["confirmation_source"] == "owner"
        assert state["sent_recorded_at_ms"] == state["reconciled_at_ms"]
        assert state["delivered_at_ms"] is None
        assert state["effects_state"] == "needs_review"
        assert state["effects_review_reason"] == "actual_delivery_time_unknown"
    assert store.mark_sent(spec.action_id, claim.token).ok is delivered
    assert client.get(store.key(spec.action_id)) == first
    assert not store.mark_unknown(spec.action_id, claim.token).ok
    assert not store.claim(spec).ok
    assert store.inspect(spec.action_id).state == ("sent" if delivered else "cancelled")


@pytest.mark.asyncio
@pytest.mark.parametrize("authorized", [False, True])
async def test_owner_private_reconciliation_works_with_autonomy_disabled(delivery, authorized, monkeypatch):
    client, store, spec = delivery
    claim = store.claim(spec)
    store.mark_unknown(spec.action_id, claim.token)
    owner = load_owner()
    ctx = SimpleNamespace(settings=SimpleNamespace(autonomy_owner_id=99),
        repository=SimpleNamespace(redis_client=client), policy=SimpleNamespace(is_enabled=lambda: False))
    event = Mock(spec=owner.PrivateMessageEvent, user_id=99 if authorized else 100)
    event.get_plaintext.return_value = f"发送核对 {spec.action_id} 放弃"
    feedback = AsyncMock()
    monkeypatch.setitem(owner.process_delivery_command.__globals__, "send_to_event", feedback)
    bot = Mock()
    assert await owner.autonomy_rule(ctx, event) is authorized
    assert await owner.process_owner_private(ctx, bot, Mock(), event, event.get_plaintext()) is authorized
    assert feedback.await_count == int(authorized)
    assert store.inspect(spec.action_id).state == ("cancelled" if authorized else "unknown")
    assert not bot.mock_calls


@pytest.mark.asyncio
async def test_group_command_cannot_reconcile(delivery):
    client, store, spec = delivery
    owner = load_owner()
    ctx = SimpleNamespace(settings=SimpleNamespace(autonomy_owner_id=99),
                          repository=SimpleNamespace(redis_client=client))
    event = SimpleNamespace(user_id=99)
    assert not await owner.process_delivery_command(ctx, Mock(), event, f"发送核对 {spec.action_id} 已送达")
    assert not client.exists(store.key(spec.action_id))


@pytest.mark.asyncio
async def test_owner_sent_feedback_keeps_time_effects_under_review(delivery, monkeypatch):
    client, store, spec = delivery
    claim = store.claim(spec)
    store.mark_unknown(spec.action_id, claim.token)
    owner = load_owner()
    ctx = SimpleNamespace(settings=SimpleNamespace(autonomy_owner_id=99),
                          repository=SimpleNamespace(redis_client=client))
    event = Mock(spec=owner.PrivateMessageEvent, user_id=99)
    feedback = AsyncMock()
    monkeypatch.setitem(owner.process_delivery_command.__globals__, "send_to_event", feedback)
    assert await owner.process_delivery_command(
        ctx, Mock(), event, f"发送核对 {spec.action_id} 已送达")
    message = feedback.await_args.args[2]
    assert "补记保留待核对" in message and "不使用核对时间代替" in message
    state = json.loads(client.get(store.key(spec.action_id)))
    assert state["state"] == "sent" and state["delivered_at_ms"] is None
    assert state["effects_state"] == "needs_review"


def test_competing_manual_conclusions_cannot_overwrite_each_other(delivery):
    client, store, spec = delivery
    claim = store.claim(spec)
    store.mark_unknown(spec.action_id, claim.token)
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda delivered: store.reconcile(
            spec.action_id, delivered=delivered, operator_id="99"), [True, False]))
    assert sum(result.ok for result in results) == 1
    assert store.inspect(spec.action_id).state == next(result.state for result in results if result.ok)
    assert client.ttl(store.key(spec.action_id)) == -1


def test_lost_reconciliation_response_preserves_idempotent_conclusion(delivery):
    client, store, spec = delivery
    claim = store.claim(spec)
    store.mark_unknown(spec.action_id, claim.token)

    def eval_with_lost_response(*args):
        result = client.eval(*args)
        if args[5] == "reconcile_sent":
            raise ConnectionError("response lost after commit")
        return result

    uncertain = DeliveryStore(SimpleNamespace(eval=eval_with_lost_response))
    with pytest.raises(DeliveryUnavailable):
        uncertain.reconcile(spec.action_id, delivered=True, operator_id="99")
    assert store.reconcile(spec.action_id, delivered=True, operator_id="99").code == "already_reconciled"
    assert not store.claim(spec).ok
