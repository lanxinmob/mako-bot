"""Command feedback preserves durable partial outcomes and never retries."""
from datetime import datetime, timedelta
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.models.schemas import ReminderRecord
from src.services.delivery.reminder import generate_job_id
from src.services.delivery.reminder import ReminderBook
from src.services.chat.policy import ChatAddress
from src.services.persistence.reminders import RemindersRepository
from test.autonomy.test_pending_atomic import isolated_redis
from test.delivery.state.test_reminder_schedule import runtime as schedule_runtime
from test.delivery.test_sender_acknowledgement import load_function


def handler(runtime, intent, *, cache_confirmed=True):
    future = datetime.now() + timedelta(hours=1)
    item = ReminderRecord(reminder_id="old", session_id="group_2", user_id=1,
                          group_id=2, content="old", remind_time=future)
    snapshot = SimpleNamespace(record=item)
    change = SimpleNamespace(cache_confirmed=cache_confirmed,
        mutation=SimpleNamespace(ok=True, delivery_state="not_started"))
    runtime.create.return_value = change
    runtime.replace.return_value = change
    send = AsyncMock()
    function = load_function("src/plugins/chat/reminders.py", "handle_reminder", {
        "datetime": datetime, "GroupMessageEvent": SimpleNamespace,
        "ReminderRecord": ReminderRecord, "generate_job_id": generate_job_id,
        "reminder_parser": SimpleNamespace(parse=AsyncMock(return_value={
            "intent": intent, "content": "new", "remind_time": future,
            "target_content": "old", "new_content": "new", "new_remind_time": future,
        })),
        "_parse_remind_time": lambda value: value, "_runtime": AsyncMock(return_value=runtime),
        "_find_snapshot": AsyncMock(return_value=snapshot), "send_to_event": send,
        "logger": Mock(),
    })
    return function, send


@pytest.mark.asyncio
@pytest.mark.parametrize("cache_confirmed", [False, True])
async def test_modify_reports_persisted_but_unscheduled_separately(cache_confirmed):
    runtime = SimpleNamespace(create=AsyncMock(), replace=AsyncMock())
    function, send = handler(runtime, "MODIFY", cache_confirmed=cache_confirmed)
    await function(object(), SimpleNamespace(self_id="99", user_id=1, group_id=2),
                   ChatAddress("group", 1, 2), "modify")
    runtime.replace.assert_awaited_once()
    runtime.create.assert_not_awaited()
    assert runtime.replace.call_args.args[1].reminder_id == "old"
    reply = send.call_args.args[2]
    assert ("提醒已更新" in reply) is cache_confirmed
    assert ("调度尚未确认" in reply) is not cache_confirmed


@pytest.mark.asyncio
@pytest.mark.parametrize("intent", ["CREATE", "MODIFY"])
async def test_persistence_failure_reports_uncertainty_without_retry(intent):
    runtime = SimpleNamespace(create=AsyncMock(), replace=AsyncMock())
    function, send = handler(runtime, intent)
    operation = runtime.create if intent == "CREATE" else runtime.replace
    operation.side_effect = OSError("write response unknown")
    assert await function(object(), SimpleNamespace(self_id="99", user_id=1, group_id=2),
                          ChatAddress("group", 1, 2), "fixture")
    operation.assert_awaited_once()
    reply = send.call_args.args[2]
    assert "结果未确认" in reply and "勿重复" in reply


@pytest.mark.asyncio
@pytest.mark.parametrize("temporary", [False, True])
async def test_private_create_list_modify_cancel_and_session_isolation(isolated_redis, temporary):
    lifecycle, _, jobs = schedule_runtime(isolated_redis)
    repository = RemindersRepository(SimpleNamespace(redis=isolated_redis))
    book = ReminderBook(storage=repository)
    future = datetime.now() + timedelta(hours=1)
    for reminder_id, address, owner, group, content in [
        ("group", "group_2", 7, 2, "群里喝水"),
        ("other-user", "private_8", 8, 0, "别人喝水"),
    ]:
        await lifecycle.create(ReminderRecord(reminder_id=reminder_id, session_id=address,
            user_id=owner, group_id=group, content=content, remind_time=future), "99")
    find = load_function("src/plugins/chat/reminders.py", "_find_snapshot", {
        "asyncio": asyncio, "reminder_book": book,
    })
    parse = AsyncMock(return_value={"intent": "CREATE", "content": "喝水", "remind_time": future})
    replies = AsyncMock()
    handle = load_function("src/plugins/chat/reminders.py", "handle_reminder", {
        "datetime": datetime, "ReminderRecord": ReminderRecord, "generate_job_id": generate_job_id,
        "reminder_parser": SimpleNamespace(parse=parse), "_parse_remind_time": lambda value: value,
        "_runtime": AsyncMock(return_value=lifecycle), "_find_snapshot": find,
        "send_to_event": replies, "logger": Mock(),
    })
    event, address = SimpleNamespace(user_id=7, self_id="99"), ChatAddress("private", 7)
    if temporary:
        event.group_id = 2
        address = ChatAddress("private", 7, 2)
    assert await handle(object(), event, address, "一小时后提醒我喝水")
    listed = book.list(address.session_id, user_id=7)
    assert len(listed) == 1 and listed[0].content == "喝水" and listed[0].group_id == 0
    job_id = listed[0].job_id
    original = lifecycle.source.load(job_id)
    assert original.record.delivery_target == ("private", 7) and job_id in jobs
    assert "记下啦" in replies.call_args.args[2]

    # A keyword from another session or owner must not select that reminder.
    for keyword in ("群里喝水", "别人喝水"):
        parse.return_value = {"intent": "DELETE", "target_content": keyword}
        await handle(object(), event, address, "取消 " + keyword)
        assert "未找到" in replies.call_args.args[2]
    assert lifecycle.source.load("group") is not None
    assert lifecycle.source.load("other-user") is not None

    parse.return_value = {"intent": "MODIFY", "target_content": "喝水",
                          "new_content": "喝茶", "new_remind_time": future + timedelta(minutes=10)}
    await handle(object(), event, address, "把喝水提醒改成喝茶")
    current = lifecycle.source.load(job_id)
    assert current.record.content == "喝茶" and current.revision != original.revision
    assert current.record.remind_time == future + timedelta(minutes=10)
    assert current.record.delivery_target == ("private", 7)
    assert "提醒已更新" in replies.call_args.args[2]
    parse.return_value = {"intent": "DELETE", "target_content": "喝茶"}
    await handle(object(), event, address, "取消喝茶提醒")
    assert lifecycle.source.load(job_id) is None and job_id not in jobs
    assert book.list(address.session_id, user_id=7) == []
    assert "已取消" in replies.call_args.args[2]
