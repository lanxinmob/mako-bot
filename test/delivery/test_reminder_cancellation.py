"""Actual dispatch and Redis cancellation interleavings through the command."""
import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.services.delivery.dispatcher import OutboundDispatcher
from src.services.delivery.reminder_delivery import ReminderDelivery
from test.autonomy.test_pending_atomic import isolated_redis
from test.delivery.state.test_reminder_schedule import runtime
from test.delivery.state.test_reminder_source import record
from test.delivery.test_sender_acknowledgement import load_function


@pytest.mark.asyncio
@pytest.mark.parametrize("in_flight", [False, True])
async def test_delete_cancels_queued_reminder_and_reports_in_flight(isolated_redis, in_flight):
    lifecycle, scheduler, jobs = runtime(isolated_redis)
    old = (await lifecycle.create(record(isolated_redis), "99")).mutation.snapshot
    dispatcher = OutboundDispatcher(spacing=0)
    entered, release, queued = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def hold():
        entered.set()
        await release.wait()

    async def transport(**kwargs):
        if in_flight:
            await hold()
        return {"message_id": 1}

    async def schedule(kind, target, send, **kwargs):
        queued.set()
        return await dispatcher.dispatch(kind, target, send, **kwargs)

    bot = SimpleNamespace(self_id="99", send_group_msg=AsyncMock(side_effect=transport))
    delivery = ReminderDelivery(isolated_redis, schedule=schedule)
    replies = AsyncMock()
    handle = load_function("src/plugins/chat/reminders.py", "handle_reminder", {
        "datetime": datetime, "GroupMessageEvent": SimpleNamespace,
        "reminder_parser": SimpleNamespace(parse=AsyncMock(return_value={
            "intent": "DELETE", "target_content": "body",
        })),
        "_runtime": AsyncMock(return_value=lifecycle),
        "_find_snapshot": AsyncMock(return_value=old),
        "send_to_event": replies, "logger": Mock(),
    })
    blocker = None
    if not in_flight:
        blocker = asyncio.create_task(dispatcher.dispatch("group", 1, hold, category="command"))
        await asyncio.wait_for(entered.wait(), 5)
    task = asyncio.create_task(delivery.deliver(bot, "fixture", old.revision, valid_until_ms=2**52))
    try:
        await asyncio.wait_for(entered.wait() if in_flight else queued.wait(), 5)
        await handle(object(), SimpleNamespace(user_id=7, group_id=1, self_id="99"),
                     SimpleNamespace(session_id="group_1"), "delete")
    finally:
        release.set()
        await asyncio.wait_for(task, 5)
        if blocker:
            await asyncio.wait_for(blocker, 5)
    assert bot.send_group_msg.await_count == int(in_flight)
    assert lifecycle.source.load("fixture") is None
    assert ("无法撤回" in replies.call_args.args[2]) is in_flight
    assert not jobs


@pytest.mark.asyncio
async def test_old_acknowledgement_does_not_delete_replacement(isolated_redis):
    lifecycle, scheduler, jobs = runtime(isolated_redis)
    old = (await lifecycle.create(record(isolated_redis), "99")).mutation.snapshot

    async def transport(**kwargs):
        change = await lifecycle.replace(old, old.record.model_copy(update={"content": "new"}), "99")
        assert change.mutation.ok
        return {"message_id": 1}

    bot = SimpleNamespace(self_id="99", send_group_msg=AsyncMock(side_effect=transport))

    async def schedule(kind, target, send, **kwargs):
        return await send()

    delivery = ReminderDelivery(isolated_redis, schedule=schedule)
    callback = load_function("src/plugins/chat/reminders.py", "send_group_reminder", {
        "asyncio": asyncio, "_runtime": AsyncMock(return_value=lifecycle),
        "get_bot": Mock(return_value=bot), "ReminderDelivery": Mock(return_value=delivery), "logger": Mock(),
    })
    await callback("fixture", old.revision, 2**52)
    bot.send_group_msg.assert_awaited_once()
    current = lifecycle.source.load("fixture")
    assert current.record.content == "new"
    assert current.revision != old.revision
    assert jobs["fixture"].args[1] == current.revision
