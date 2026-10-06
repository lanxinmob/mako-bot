import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.services.delivery.periodic import PeriodicDelivery
from src.services.delivery.reminder_delivery import ReminderDelivery
from src.services.delivery.state import DeliverySpec
from src.services.delivery.state.recovery import DeliveryRecovery
from test.autonomy.test_pending_atomic import isolated_redis
from test.delivery.state.test_followups import setup as followup_setup
from test.delivery.state.test_reminder_source import record
from test.delivery.state.test_store import delivery, expire
from src.services.persistence.reminder_state import ReminderStateStore


async def immediate(kind, target, send, **kwargs):
    return await send()


def test_recovery_never_creates_missing_record_or_reclaims_unknown(delivery):
    client, store, spec = delivery
    assert store.recover(spec).code == "missing"
    assert not client.exists(store.key(spec.action_id))
    claim = store.claim(spec)
    assert store.recover(spec).code == "busy"
    expire(client, store, spec)
    resumed = store.recover(spec)
    assert resumed.ok and resumed.token != claim.token
    assert not store.begin_send(spec, claim.token).ok
    assert store.begin_send(spec, resumed.token).ok
    expire(client, store, spec)
    assert not store.recover(spec).ok
    assert store.inspect(spec.action_id).state == "unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["reminder", "followup", "periodic"])
@pytest.mark.parametrize("lose_record", [False, True])
async def test_three_senders_resume_frozen_record_but_never_recreate_it(isolated_redis, kind, lose_record):
    client = isolated_redis
    rejected = AsyncMock(return_value=False)
    if kind == "reminder":
        snapshot = ReminderStateStore(client).create(record(client), bot_id="99").snapshot
        service = ReminderDelivery(client, schedule=rejected)
        bot = SimpleNamespace(self_id="99", send_group_msg=AsyncMock(return_value={"message_id": 1}))

        async def call(spec=None):
            return await service.deliver(bot, "fixture", snapshot.revision,
                valid_until_ms=2**52, recovery_spec=spec)
    elif kind == "followup":
        _, memory, service, bot = followup_setup(client)
        service.schedule = rejected

        async def call(spec=None):
            return await service.deliver(bot, 7, memory.memory_id, recovery_spec=spec)
    else:
        service = PeriodicDelivery(client, Mock(), Mock(check=Mock(return_value=SimpleNamespace(allowed=True))),
                                   schedule=rejected)
        bot = SimpleNamespace(self_id="99", send_group_msg=AsyncMock(return_value={"message_id": 1}))
        period = datetime.now(timezone.utc).date()

        async def call(spec=None):
            return await service.deliver(bot, 1, "frozen body", task="scheduler.good_morning",
                period=period, timezone=timezone.utc, intent="greeting", recovery_spec=spec)

    assert not await call()
    action_keys = [key for key in client.scan_iter(match="mako:delivery:v1:*")
                   if len(key) == len("mako:delivery:v1:") + 64]
    assert len(action_keys) == 1
    key = action_keys[0]
    spec = DeliverySpec(**json.loads(json.loads(client.get(key))["spec_json"]))
    service.schedule = immediate

    def allowed(_spec):
        if lose_record:
            client.delete(key)  # Synthetic loss after inspection, before recovery claim.
        return True

    runner = DeliveryRecovery(client, {kind: lambda _bot, frozen: call(frozen)},
                              bot_lookup=lambda _: bot, allowed=allowed)
    result = await runner.recover(spec.action_id)
    transport = bot.send_private_msg if kind == "followup" else bot.send_group_msg
    assert transport.await_count == int(not lose_record)
    assert result == ("not_confirmed" if lose_record else "sent")
    if lose_record:
        assert not client.exists(key)
    else:
        assert service.store.inspect(spec.action_id).state == "sent"
        assert await runner.recover(spec.action_id) == "blocked"


@pytest.mark.asyncio
async def test_busy_terminal_and_wrong_bot_never_invoke_handler(delivery):
    _, store, spec = delivery
    handler = AsyncMock(return_value=True)
    bot = SimpleNamespace(self_id="other")
    runner = DeliveryRecovery(store.redis, {spec.kind: handler}, bot_lookup=lambda _: bot, allowed=lambda _: True)
    claim = store.claim(spec)
    assert await runner.recover(spec.action_id) == "busy"
    assert store.reject_before_send(spec.action_id, claim.token).ok
    assert await runner.recover(spec.action_id) == "bot_unavailable"
    runner.allowed = lambda _: False
    assert await runner.recover(spec.action_id) == "disabled"
    handler.assert_not_awaited()
