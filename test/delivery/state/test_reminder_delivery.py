from types import SimpleNamespace
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from src.services.delivery.reminder_delivery import ReminderDelivery, reminder_spec
from src.services.delivery.effects.producer import production_plan
from src.services.persistence.reminder_state import ReminderStateStore
from test.autonomy.test_pending_atomic import isolated_redis
from test.delivery.state.test_reminder_source import record


async def immediate(target_type, target_id, send, **kwargs):
    return await send()


def setup(client, schedule=immediate, *, target_type="group"):
    source = ReminderStateStore(client)
    snapshot = source.create(record(client, target_type=target_type), bot_id="99").snapshot
    bot = SimpleNamespace(self_id="99", send_group_msg=AsyncMock(return_value={"message_id": 1}),
                          send_private_msg=AsyncMock(return_value={"message_id": 2}))
    return source, snapshot, bot, ReminderDelivery(client, schedule=schedule)


@pytest.mark.asyncio
@pytest.mark.parametrize("target_type", ["group", "private"])
async def test_confirmed_send_completes_once(isolated_redis, target_type):
    source, snapshot, bot, delivery = setup(isolated_redis, target_type=target_type)
    assert await delivery.deliver(bot, "fixture", snapshot.revision, valid_until_ms=2**52)
    assert source.load("fixture") is None
    assert not await delivery.deliver(bot, "fixture", snapshot.revision, valid_until_ms=2**52)
    transport = bot.send_private_msg if target_type == "private" else bot.send_group_msg
    transport.assert_awaited_once()
    kwargs = transport.call_args.kwargs
    assert kwargs["user_id" if target_type == "private" else "group_id"] == (7 if target_type == "private" else 1)
    assert kwargs["message"].extract_plain_text() == snapshot.record.content
    (bot.send_group_msg if target_type == "private" else bot.send_private_msg).assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("target_type", ["group", "private"])
async def test_cancel_after_queue_admission_prevents_transport(isolated_redis, target_type):
    source, snapshot, bot, delivery = setup(isolated_redis, target_type=target_type)

    async def queued(target_type, target_id, send, **kwargs):
        assert source.cancel(snapshot).ok
        return await send()

    delivery.schedule = queued
    assert not await delivery.deliver(bot, "fixture", snapshot.revision, valid_until_ms=2**52)
    bot.send_group_msg.assert_not_awaited()
    bot.send_private_msg.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("target_type", ["group", "private"])
async def test_unknown_ack_never_retries_same_revision(isolated_redis, target_type):
    source, snapshot, bot, delivery = setup(isolated_redis, target_type=target_type)
    transport = bot.send_private_msg if target_type == "private" else bot.send_group_msg
    transport.return_value = {}
    assert not await delivery.deliver(bot, "fixture", snapshot.revision, valid_until_ms=2**52)
    assert not await delivery.deliver(bot, "fixture", snapshot.revision, valid_until_ms=2**52)
    assert source.load("fixture") == snapshot
    spec = reminder_spec(snapshot, valid_until_ms=2**52)
    assert not await delivery.deliver(bot, "fixture", snapshot.revision,
                                     valid_until_ms=2**52, recovery_spec=spec)
    assert delivery.store.inspect(spec.action_id).state == "unknown"
    transport.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("target_type", ["group", "private"])
async def test_late_ack_preserves_replacement(isolated_redis, target_type):
    source, snapshot, bot, delivery = setup(isolated_redis, target_type=target_type)

    async def transport(**kwargs):
        assert source.replace(snapshot, snapshot.record.model_copy(update={"content": "new"}), bot_id="99").ok
        return {"message_id": 1}

    (bot.send_private_msg if target_type == "private" else bot.send_group_msg).side_effect = transport
    assert await delivery.deliver(bot, "fixture", snapshot.revision, valid_until_ms=2**52)
    current = source.load("fixture")
    assert current.record.content == "new" and current.revision != snapshot.revision


@pytest.mark.asyncio
@pytest.mark.parametrize("target_type", ["group", "private"])
async def test_wrong_bot_or_stale_callback_cannot_send(isolated_redis, target_type):
    source, snapshot, bot, delivery = setup(isolated_redis, target_type=target_type)
    bot.self_id = "100"
    assert not await delivery.deliver(bot, "fixture", snapshot.revision, valid_until_ms=2**52)
    bot.self_id = "99"
    assert not await delivery.deliver(bot, "fixture", "old", valid_until_ms=2**52)
    assert source.load("fixture") == snapshot
    bot.send_group_msg.assert_not_awaited()
    bot.send_private_msg.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("target_type", ["group", "private"])
async def test_recovery_uses_frozen_target_and_rejects_changed_destination(isolated_redis, target_type):
    source, snapshot, bot, delivery = setup(isolated_redis, target_type=target_type)
    spec = reminder_spec(snapshot, valid_until_ms=2**52)
    claim = delivery.store.claim(spec, plan=production_plan(spec))
    assert claim.ok
    assert delivery.store.reject_before_send(spec.action_id, claim.token).ok
    for changed in (replace(spec, target_id="8"),
                    replace(spec, target_type="private" if target_type == "group" else "group")):
        assert not await delivery.deliver(bot, "fixture", snapshot.revision,
                                         valid_until_ms=2**52, recovery_spec=changed)
    assert source.load("fixture") == snapshot
    bot.send_private_msg.assert_not_awaited()
    bot.send_group_msg.assert_not_awaited()
    assert await delivery.deliver(bot, "fixture", snapshot.revision,
                                 valid_until_ms=2**52, recovery_spec=spec)
    assert source.load("fixture") is None
    (bot.send_private_msg if target_type == "private" else bot.send_group_msg).assert_awaited_once()
