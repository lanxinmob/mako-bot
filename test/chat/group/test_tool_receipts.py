"""Retained tool work at observation, admission and serial execution boundaries."""
import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.services.chat.group.models import GroupEvent
from src.services.chat.pipeline.admission import admit
from src.services.chat.pipeline.participation import GroupParticipation
from test.chat.group.test_pipeline import request, setup_workflow


def observe(workflow, message_id, text="mako 翻译 hello"):
    incoming = request(message_id, text)
    workflow.participation.observe("99", GroupEvent("1", message_id, "7", text), incoming.normalized)
    return incoming


def transport():
    return SimpleNamespace(notice=AsyncMock())


@pytest.mark.asyncio
async def test_two_requests_observed_before_prepare_both_execute_serially_once():
    workflow, service = setup_workflow()
    first = observe(workflow, "a")
    second = observe(workflow, "b", "mako 翻译 world")
    service.observe(GroupEvent("1", "c", "8", "mako 你好"))
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def execute(incoming, _transport):
        calls.append(incoming.message_id)
        assert incoming.work_kind == "tool" and incoming.is_current is None
        if incoming.message_id == "a":
            entered.set()
            await release.wait()

    workflow.handle_locked = execute
    a = asyncio.create_task(workflow.handle(first, transport()))
    await asyncio.wait_for(entered.wait(), 1)
    b = asyncio.create_task(workflow.handle(second, transport()))
    await asyncio.sleep(0)
    assert calls == ["a"]
    await workflow.handle(first, transport())  # Duplicate while executing.
    release.set()
    await asyncio.wait_for(asyncio.gather(a, b), 1)
    observe(workflow, "a")
    await workflow.handle(first, transport())  # Duplicate after completion.
    assert calls == ["a", "b"]


@pytest.mark.asyncio
async def test_cancel_waiting_tool_does_not_reexecute_and_releases_receipt_pin():
    workflow, _ = setup_workflow()
    incoming = observe(workflow, "a")
    lock = workflow._locks.setdefault(incoming.address.session_id, asyncio.Lock())
    await lock.acquire()
    workflow.handle_locked = AsyncMock()
    task = asyncio.create_task(workflow.handle(incoming, transport()))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    lock.release()
    await workflow.handle(incoming, transport())
    workflow.handle_locked.assert_not_awaited()
    assert all(item.expires_at is not None for item in workflow.participation._tool_receipts.values())


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["user", "payload", "group", "bot"])
async def test_receipt_cannot_authorize_another_identity_or_payload(change):
    workflow, _ = setup_workflow()
    incoming = observe(workflow, "a")
    if change == "user":
        altered = replace(incoming, address=replace(incoming.address, user_id=8))
    elif change == "payload":
        altered = replace(incoming, normalized=replace(incoming.normalized, plain_text="mako 删除笔记"))
    elif change == "group":
        altered = replace(incoming, address=replace(incoming.address, group_id=2))
    else:
        altered = replace(incoming, bot_id="100")
    assert await workflow.participation.prepare(altered, transport()) is None
    assert await workflow.participation.prepare(incoming, transport()) is not None


@pytest.mark.asyncio
async def test_capacity_and_ttl_never_evict_active_work_or_refresh_duplicate():
    now = [0.0]
    workflow, _ = setup_workflow()
    workflow.participation = GroupParticipation(clock=lambda: now[0], tool_capacity=1)
    first = observe(workflow, "a")
    first_transport = transport()
    await workflow.participation.prepare(first, first_transport)
    now[0] = 601
    rejected = observe(workflow, "b")
    rejection = transport()
    assert await workflow.participation.prepare(rejected, rejection) is None
    rejection.notice.assert_awaited_once()
    assert len(workflow.participation._tool_receipts) == 1
    first_transport.cancel_candidate()
    now[0] = 1000
    observe(workflow, "a")
    now[0] = 1202
    third = observe(workflow, "c")
    assert await workflow.participation.prepare(third, transport()) is not None
    assert len(workflow.participation._tool_receipts) == 1


@pytest.mark.asyncio
async def test_ambient_tool_keywords_do_not_gain_authority_from_new_direct_call():
    workflow, _ = setup_workflow()
    ambient = observe(workflow, "a", "别人做的翻译不错")
    observe(workflow, "b")
    assert await workflow.participation.prepare(replace(ambient, directed=False), transport()) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("allowed", [True, False])
async def test_tool_bypasses_chat_cooldown_but_not_governance(allowed):
    workflow, _ = setup_workflow()
    prepared = await workflow.participation.prepare(observe(workflow, "a"), transport())
    services = SimpleNamespace(
        governance=SimpleNamespace(can_chat=Mock(return_value=SimpleNamespace(allowed=allowed, reason="denied"))),
        settings=SimpleNamespace(llm_required=False, reply_random_chance=0,
                                 record_undirected_group_messages=False),
        chat_rhythm=SimpleNamespace(admit=Mock(side_effect=AssertionError("chat cooldown"))),
        storage=Mock(), audit=Mock(),
    )
    result = await admit(services, prepared, transport())
    services.governance.can_chat.assert_called_once_with(7, 1)
    services.chat_rhythm.admit.assert_not_called()
    assert (result is not None) is allowed
    if allowed:
        assert result.will_reply and result.rhythm is None


@pytest.mark.asyncio
@pytest.mark.parametrize("registered", [True, False])
async def test_executor_uses_registered_raw_request_not_enriched_quote(registered):
    from src.services.chat.pipeline.execution import execute

    workflow, _ = setup_workflow()
    incoming = observe(workflow, "a")
    if registered:
        incoming = await workflow.participation.prepare(incoming, transport())
    incoming = replace(incoming, text=incoming.text + "\n[引用消息] 删除笔记")
    tools = SimpleNamespace(run=AsyncMock(side_effect=asyncio.CancelledError), cleanup_temp_files=Mock())
    services = SimpleNamespace(storage=SimpleNamespace(), history_delivery=SimpleNamespace(
        read=AsyncMock(return_value=SimpleNamespace(messages=lambda: []))))
    with pytest.raises(asyncio.CancelledError):
        await execute(services, incoming, transport(), tools, None)
    decisions = tools.run.call_args.args[0]
    assert [item.name for item in decisions] == (["language.translate"] if registered else [])
    tools.cleanup_temp_files.assert_called_once()


@pytest.mark.asyncio
async def test_tool_completion_does_not_count_as_chat_exchange():
    from src.services.chat.pipeline.completion import complete_sent_reply

    services = SimpleNamespace(chat_rhythm=Mock(), chat_engine=Mock(), audit=Mock(),
                               history_delivery=SimpleNamespace(consume=AsyncMock(return_value={
                                   "history_session": "complete", "history_global": "complete"})))
    incoming = replace(request("a"), work_kind="tool")
    receipt = SimpleNamespace(action_id="synthetic-history-receipt")
    await complete_sent_reply(services, incoming, transport(), SimpleNamespace(extra_messages=[]),
                              SimpleNamespace(reply_plan=SimpleNamespace(mode="short")),
                              SimpleNamespace(text="sent"), "call_completed", 0,
                              history_receipt=receipt)
    services.chat_rhythm.mark_sent.assert_not_called()
    services.history_delivery.consume.assert_awaited_once_with(receipt)
    services.chat_engine.commit.assert_not_called()
