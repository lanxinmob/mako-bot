"""Concurrency and delivery contracts across the refactored chat boundary."""
import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.services.chat.pipeline.models import ChatInput
from src.services.chat.pipeline.workflow import ChatWorkflow
from src.services.chat.pipeline import execution
from src.services.chat.context import EnrichedChatInput
from src.services.chat.models import ChatReply
from src.services.chat.policy import ChatAddress
from src.services.tools.models import ToolExecutionResult
from src.utils.message import NormalizedMessage
from test.chat.history_delivery.fixtures import history_double


def incoming(group=1, user=7, text="hello"):
    return ChatInput(ChatAddress("group", user, group), "fixture", text,
                     NormalizedMessage(), True, False, 0.0)


@pytest.mark.asyncio
async def test_cancel_latest_batch_does_not_leak_into_next_message():
    workflow = ChatWorkflow(SimpleNamespace(settings=SimpleNamespace(chat_reply_debounce_seconds=.01)))
    workflow.handle_locked = AsyncMock()
    task = asyncio.create_task(workflow.handle(incoming(text="cancelled"), None))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not workflow._pending
    await workflow.handle(replace(incoming(text="next"), started_at=10), "next")
    request, transport = workflow.handle_locked.call_args.args
    assert (request.text, request.started_at, transport) == ("next", 10, "next")


@pytest.mark.asyncio
async def test_cancel_old_waiter_preserves_new_batch():
    workflow = ChatWorkflow(SimpleNamespace(settings=SimpleNamespace(chat_reply_debounce_seconds=.01)))
    workflow.handle_locked = AsyncMock()
    old = asyncio.create_task(workflow.handle(incoming(text="first"), "old"))
    await asyncio.sleep(0)
    new = asyncio.create_task(workflow.handle(incoming(text="second"), "new"))
    await asyncio.sleep(0)
    old.cancel()
    with pytest.raises(asyncio.CancelledError):
        await old
    await new
    request, transport = workflow.handle_locked.call_args.args
    assert (request.text, transport) == ("first\nsecond", "new")
    assert not workflow._pending


@pytest.mark.asyncio
async def test_old_waiter_cannot_claim_new_batch_with_reused_version(monkeypatch):
    from src.services.chat.pipeline import workflow as module

    gates = [asyncio.Event() for _ in range(3)]
    entered = [asyncio.Event() for _ in range(3)]
    count = 0

    async def sleep(_delay):
        nonlocal count
        index = count
        count += 1
        entered[index].set()
        await gates[index].wait()

    monkeypatch.setattr(module, "asyncio", SimpleNamespace(Lock=asyncio.Lock, sleep=sleep))
    workflow = ChatWorkflow(SimpleNamespace(settings=SimpleNamespace(chat_reply_debounce_seconds=1)))
    workflow.handle_locked = AsyncMock()
    old = asyncio.create_task(workflow.handle(incoming(text="old"), None))
    await entered[0].wait()
    replacement = asyncio.create_task(workflow.handle(incoming(text="replacement"), None))
    await entered[1].wait()
    replacement.cancel()
    with pytest.raises(asyncio.CancelledError):
        await replacement
    new = asyncio.create_task(workflow.handle(incoming(text="new"), "new"))
    await entered[2].wait()
    gates[0].set()
    await old
    workflow.handle_locked.assert_not_awaited()
    assert len(workflow._pending) == 1
    gates[2].set()
    await new
    assert workflow.handle_locked.call_args.args[0].text == "new"
    assert not workflow._pending


@pytest.mark.asyncio
async def test_interleaved_speakers_keep_text_and_latest_transport_together():
    workflow = ChatWorkflow(SimpleNamespace(settings=SimpleNamespace(chat_reply_debounce_seconds=.01)))
    seen = []

    async def receive(request, transport):
        seen.append((request.address.user_id, request.text, transport, request.started_at))

    workflow.handle_locked = receive
    await asyncio.gather(
        workflow.handle(incoming(text="first"), "old"),
        workflow.handle(incoming(user=8, text="other"), "other"),
        workflow.handle(replace(incoming(text="second"), started_at=5), "new"),
    )
    assert sorted(seen) == [(7, "first\nsecond", "new", 0.0), (8, "other", "other", 0.0)]


@pytest.mark.asyncio
async def test_different_groups_can_progress_without_waiting_for_one_group():
    workflow = ChatWorkflow(SimpleNamespace(settings=SimpleNamespace(chat_reply_debounce_seconds=0)))
    entered = asyncio.Event()
    release = asyncio.Event()
    seen = []

    async def receive(request, _transport):
        if request.text == "hold":
            entered.set()
            await release.wait()
        seen.append(request.text)

    workflow.handle_locked = receive
    first = asyncio.create_task(workflow.handle(incoming(text="hold"), None))
    await asyncio.wait_for(entered.wait(), 1)
    same = asyncio.create_task(workflow.handle(incoming(text="same"), None))
    await asyncio.wait_for(workflow.handle(incoming(group=2, text="other"), None), 1)
    assert seen == ["other"]
    release.set()
    await asyncio.gather(first, same)
    assert seen == ["other", "hold", "same"]


@pytest.mark.asyncio
@pytest.mark.parametrize("send_fails", [False, True, "rejected", "missing_ack"])
async def test_commit_follows_delivery_and_failed_send_still_cleans_files(monkeypatch, send_fails):
    order = []
    transport = SimpleNamespace(notice=AsyncMock(), extra=AsyncMock())

    async def reply(_text):
        order.append("send")
        if send_fails == "rejected":
            return False
        if send_fails == "missing_ack":
            return None
        if send_fails:
            raise RuntimeError("synthetic send failure")
        return True

    transport.reply = reply
    plan = SimpleNamespace(max_chars=80, mode="short", social_state="normal")
    plugin_rows = [{"role": "assistant", "content": "已发送的期刊标题与 DOI",
                    "category": "command", "message_id": "41", "sent_at_ms": 1000}]
    monkeypatch.setattr(execution, "select_reply_plan", lambda *_a, **_k: plan)
    monkeypatch.setattr(execution, "remaining_reply_delay", lambda *_a: 0)
    monkeypatch.setattr(execution, "decide_intents", lambda *_a, **_k: [])
    services = SimpleNamespace(
        history_delivery=history_double(order=order),
        storage=SimpleNamespace(get_history=Mock(return_value=[]),
                                get_plugin_history=Mock(return_value=plugin_rows)),
        context_builder=SimpleNamespace(build=AsyncMock(return_value=EnrichedChatInput("hello", "hello"))),
        chat_engine=SimpleNamespace(
            generate=AsyncMock(return_value=ChatReply("reply", [], "fake")),
            commit=Mock(side_effect=lambda *_a: order.append("commit"))),
        governance=SimpleNamespace(estimate_llm_cost=Mock(return_value=0),
                                   can_consume_cost=Mock(return_value=SimpleNamespace(allowed=True)),
                                   consume_cost=Mock()),
        audit=Mock(), chat_rhythm=Mock(),
    )
    tools = SimpleNamespace(run=AsyncMock(return_value=ToolExecutionResult()), cleanup_temp_files=Mock())
    read_context = Mock(return_value="fresh group context")
    await execution.execute(services, replace(incoming(), group_context="stale group context",
                                             read_group_context=read_context), transport, tools, None)
    read_context.assert_called_once()
    generated_request = services.chat_engine.generate.call_args.args[0]
    assert generated_request.history == []
    assert generated_request.plugin_history == plugin_rows
    assert services.context_builder.build.call_args.kwargs["history"] == plugin_rows
    assert "fresh group context" in generated_request.llm_text
    assert "stale group context" not in generated_request.llm_text
    assert order == (["send"] if send_fails else ["send", "commit"])
    tools.cleanup_temp_files.assert_called_once()
    assert transport.notice.await_count == int(send_fails is True)
    services.governance.consume_cost.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["context", "budget", "generation", "delay"])
async def test_request_refreshes_before_freezing_and_rejects_later_changes(monkeypatch, stage):
    from src.services.chat.group.models import GroupEvent
    from test.chat.group.test_pipeline import setup_workflow, request

    workflow, group = setup_workflow()
    group.observe(GroupEvent("1", "a", "7", "mako 你好"))
    transport = SimpleNamespace(reply=AsyncMock(return_value=True), notice=AsyncMock())
    prepared = await workflow.participation.prepare(request("a"), transport)

    def supplement():
        group.observe(GroupEvent("1", "b", "8", "新的补充信息"))

    async def generate(_request):
        if stage == "generation":
            supplement()
        return ChatReply("old body", [], "fake")

    async def build_context(**_kwargs):
        if stage == "context":
            supplement()
        return EnrichedChatInput("hello", "hello")

    governance = SimpleNamespace(estimate_llm_cost=Mock(return_value=0),
                                 can_consume_cost=Mock(return_value=SimpleNamespace(allowed=True)),
                                 consume_cost=Mock())

    async def to_thread(function, *args):
        if stage == "budget" and function is governance.can_consume_cost:
            supplement()
        return function(*args)

    async def sleep(_delay):
        supplement()

    monkeypatch.setattr(execution, "asyncio", SimpleNamespace(
        to_thread=to_thread, sleep=sleep, TimeoutError=asyncio.TimeoutError))
    monkeypatch.setattr(execution, "remaining_reply_delay", lambda *_: 1 if stage == "delay" else 0)
    monkeypatch.setattr(execution, "decide_intents", lambda *_a, **_k: [])
    completion = AsyncMock()
    monkeypatch.setattr(execution, "complete_sent_reply", completion)
    services = SimpleNamespace(
        history_delivery=history_double(),
        storage=SimpleNamespace(get_history=Mock(return_value=[])),
        context_builder=SimpleNamespace(build=AsyncMock(side_effect=build_context)),
        chat_engine=SimpleNamespace(generate=AsyncMock(side_effect=generate)),
        governance=governance, audit=Mock(),
    )
    tools = SimpleNamespace(run=AsyncMock(return_value=ToolExecutionResult()), cleanup_temp_files=Mock())
    await execution.execute(services, prepared, transport, tools, None)
    if stage == "context":
        transport.reply.assert_awaited_once()
        completion.assert_awaited_once()
        generated_request = services.chat_engine.generate.call_args.args[0]
        assert "新的补充信息" in generated_request.llm_text
    else:
        transport.reply.assert_not_awaited()
        completion.assert_not_awaited()
    transport.notice.assert_not_awaited()
    tools.cleanup_temp_files.assert_called_once()
    assert services.chat_engine.generate.await_count == int(stage != "budget")
    governance.consume_cost.assert_not_called()
