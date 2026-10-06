from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.services.delivery.reminder_delivery import ReminderDelivery, reminder_spec
from src.services.persistence.reminder_state import ReminderStateStore
from test.autonomy.test_pending_atomic import isolated_redis
from test.delivery.state.test_reminder_source import record


async def immediate(target_type, target_id, send, **kwargs):
    return await send()


def setup(client, schedule=immediate):
    source = ReminderStateStore(client)
    snapshot = source.create(record(client), bot_id="99").snapshot
    bot = SimpleNamespace(self_id="99", send_group_msg=AsyncMock(return_value={"message_id": 1}))
    return source, snapshot, bot, ReminderDelivery(client, schedule=schedule)


@pytest.mark.asyncio
async def test_confirmed_send_completes_once(isolated_redis):
    source, snapshot, bot, delivery = setup(isolated_redis)
    assert await delivery.deliver(bot, "fixture", snapshot.revision, valid_until_ms=2**52)
    assert source.load("fixture") is None
    assert not await delivery.deliver(bot, "fixture", snapshot.revision, valid_until_ms=2**52)
    bot.send_group_msg.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancel_after_queue_admission_prevents_transport(isolated_redis):
    source, snapshot, bot, delivery = setup(isolated_redis)

    async def queued(target_type, target_id, send, **kwargs):
        assert source.cancel(snapshot).ok
        return await send()

    delivery.schedule = queued
    assert not await delivery.deliver(bot, "fixture", snapshot.revision, valid_until_ms=2**52)
    bot.send_group_msg.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_ack_never_retries_same_revision(isolated_redis):
    source, snapshot, bot, delivery = setup(isolated_redis)
    bot.send_group_msg.return_value = {}
    assert not await delivery.deliver(bot, "fixture", snapshot.revision, valid_until_ms=2**52)
    assert not await delivery.deliver(bot, "fixture", snapshot.revision, valid_until_ms=2**52)
    assert source.load("fixture") == snapshot
    spec = reminder_spec(snapshot, valid_until_ms=2**52)
    assert delivery.store.inspect(spec.action_id).state == "unknown"
    bot.send_group_msg.assert_awaited_once()


@pytest.mark.asyncio
async def test_late_ack_preserves_replacement(isolated_redis):
    source, snapshot, bot, delivery = setup(isolated_redis)

    async def transport(**kwargs):
        assert source.replace(snapshot, snapshot.record.model_copy(update={"content": "new"}), bot_id="99").ok
        return {"message_id": 1}

    bot.send_group_msg.side_effect = transport
    assert await delivery.deliver(bot, "fixture", snapshot.revision, valid_until_ms=2**52)
    current = source.load("fixture")
    assert current.record.content == "new" and current.revision != snapshot.revision


@pytest.mark.asyncio
async def test_wrong_bot_or_stale_callback_cannot_send(isolated_redis):
    source, snapshot, bot, delivery = setup(isolated_redis)
    bot.self_id = "100"
    assert not await delivery.deliver(bot, "fixture", snapshot.revision, valid_until_ms=2**52)
    bot.self_id = "99"
    assert not await delivery.deliver(bot, "fixture", "old", valid_until_ms=2**52)
    assert source.load("fixture") == snapshot
    bot.send_group_msg.assert_not_awaited()
