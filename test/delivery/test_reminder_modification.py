"""Command feedback preserves durable partial outcomes and never retries."""
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.models.schemas import ReminderRecord
from src.services.delivery.reminder import generate_job_id
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
                   SimpleNamespace(session_id="group_2"), "modify")
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
                          SimpleNamespace(session_id="group_2"), "fixture")
    operation.assert_awaited_once()
    reply = send.call_args.args[2]
    assert "结果未确认" in reply and "勿重复" in reply
