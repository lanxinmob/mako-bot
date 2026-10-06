from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from test.autonomy.test_pending_atomic import isolated_redis
from test.autonomy.test_approval import approval


@pytest.mark.parametrize("delivered", [True, False])
def test_resolve_without_pending_and_late_callback(approval, delivered):
    client, store, snapshot = approval
    claim = store.claim(snapshot, "original")
    assert store.begin_send(snapshot, claim.token, "original").ok
    assert not store.reconcile("p1", delivered=delivered).ok
    assert store.mark_unknown("p1", claim.token).ok
    client.delete("autonomy:pending:p1", "autonomy:pending:latest")
    assert store.reconcile("p1", delivered=delivered).ok
    assert store.reconcile("p1", delivered=delivered).ok
    assert not store.reconcile("p1", delivered=not delivered).ok
    assert not store.mark_sent("p1", claim.token).ok
    assert store.inspect("p1").state == ("sent" if delivered else "cancelled")


@pytest.mark.asyncio
@pytest.mark.parametrize("authorized", [True, False])
async def test_owner_recovery_available_when_autonomy_disabled(approval, authorized, monkeypatch):
    from test.autonomy.owner_loader import load_owner
    owner = load_owner()
    client, store, snapshot = approval
    claim = store.claim(snapshot, "original")
    store.begin_send(snapshot, claim.token, "original")
    store.mark_unknown("p1", claim.token)
    client.delete("autonomy:pending:p1", "autonomy:pending:latest")
    ctx = SimpleNamespace(
        settings=SimpleNamespace(autonomy_owner_id=99, autonomy_pending_ttl_seconds=300),
        repository=SimpleNamespace(redis_client=client),
        policy=SimpleNamespace(is_enabled=lambda: False),
    )
    event = Mock(spec=owner.PrivateMessageEvent, user_id=99 if authorized else 100)
    event.get_plaintext.return_value = "行动核对 p1 放弃"
    feedback = AsyncMock()
    monkeypatch.setattr(owner, "send_to_event", feedback)
    bot = Mock()
    assert await owner.autonomy_rule(ctx, event) is authorized
    assert await owner.process_owner_private(ctx, bot, Mock(), event, event.get_plaintext()) is authorized
    assert store.inspect("p1").state == ("cancelled" if authorized else "unknown")
    assert not bot.mock_calls
    assert feedback.await_count == int(authorized)


@pytest.mark.asyncio
async def test_cancel_confirmation_survives_cleanup_failure(approval, monkeypatch):
    from src.services.autonomy.approval import ApprovalUnavailable
    from test.autonomy.owner_loader import load_owner
    owner = load_owner()
    client, store, snapshot = approval
    monkeypatch.setattr(store, "cleanup", Mock(side_effect=ApprovalUnavailable))
    monkeypatch.setattr(owner, "ApprovalStore", lambda *args, **kwargs: store)
    feedback = AsyncMock()
    monkeypatch.setattr(owner, "send_to_event", feedback)
    ctx = SimpleNamespace(
        settings=SimpleNamespace(autonomy_owner_id=99, autonomy_pending_ttl_seconds=300),
        repository=SimpleNamespace(redis_client=client), policy=SimpleNamespace(is_enabled=lambda: True),
    )
    event = Mock(spec=owner.PrivateMessageEvent, user_id=99)
    assert await owner.process_owner_private(ctx, Mock(), Mock(), event, "取消")
    assert store.inspect("p1").state == "cancelled"
    assert client.get("autonomy:pending:p1") is not None
    message = feedback.call_args.args[2]
    assert "已取消" in message and "清理未确认" in message
