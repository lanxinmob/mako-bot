"""Synthetic interleaving at the real participation/workflow boundary."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.services.chat.group.models import GroupEvent
from src.services.chat.pipeline.models import ChatInput
from src.services.chat.pipeline.workflow import ChatWorkflow
from src.services.chat.policy import ChatAddress
from src.utils.message import NormalizedMessage


def request(message_id, text="mako 你好"):
    return ChatInput(ChatAddress("group", 7, 1), "fixture", text,
                     NormalizedMessage(plain_text=text), True, False, 0, "99", message_id)


def setup_workflow():
    workflow = ChatWorkflow(SimpleNamespace())
    service = workflow.participation.service("99")
    service.debounce_seconds = 0
    service.max_wait_seconds = 0
    return workflow, service


@pytest.mark.asyncio
async def test_ambient_group_does_not_enter_chat_services():
    workflow, service = setup_workflow()
    service.observe(GroupEvent("1", "a", "7", "别人今天吃什么"))
    workflow.handle_locked = AsyncMock()
    await workflow.handle(request("a", "别人今天吃什么"), SimpleNamespace())
    workflow.handle_locked.assert_not_awaited()


@pytest.mark.asyncio
async def test_answered_during_generation_invalidates_send_guard():
    workflow, service = setup_workflow()
    service.observe(GroupEvent("1", "a", "7", "mako 你好"))
    entered, release = asyncio.Event(), asyncio.Event()
    sent = []
    transport = SimpleNamespace()

    async def generate(incoming, transport):
        assert '"message_id": "a"' in incoming.group_context
        entered.set()
        await release.wait()
        if transport.guard():
            sent.append("reply")

    workflow.handle_locked = generate
    task = asyncio.create_task(workflow.handle(request("a"), transport))
    await asyncio.wait_for(entered.wait(), 1)
    service.observe(GroupEvent("1", "b", "8", "我已经回答了", reply_to_message_id="a"))
    release.set()
    await task
    assert sent == []


@pytest.mark.asyncio
async def test_explicit_tool_is_not_a_disposable_chat_candidate(monkeypatch):
    from src.services.chat.pipeline import participation

    workflow, service = setup_workflow()
    monkeypatch.setattr(participation, "decide_intents",
                        lambda *_a, **_kw: [SimpleNamespace(name="language.translate")])
    workflow.participation.observe("99", GroupEvent("1", "a", "7", "mako 翻译hello"))
    transport = SimpleNamespace(cancel_candidate=lambda: None)
    workflow.handle_locked = AsyncMock()
    await workflow.handle(request("a", "mako 翻译hello"), transport)
    incoming = workflow.handle_locked.call_args.args[0]
    assert incoming.is_current is None
    assert transport.category == "command"
    assert service.window.get("1").candidate is None
    transport.on_sent({"message_id": "tool-result"}, "翻译结果")
    outbound = service.snapshot("1").events[-1]
    assert outbound.text == "翻译结果" and outbound.kind == "tool"
    assert outbound.reply_to_message_id == "a"


@pytest.mark.asyncio
async def test_confirmation_after_new_user_call_does_not_claim_successor():
    workflow, service = setup_workflow()
    service.observe(GroupEvent("1", "a", "7", "mako 你好"))
    old_transport = SimpleNamespace()
    await workflow.participation.prepare(request("a"), old_transport)
    service.observe(GroupEvent("1", "new", "8", "mako 帮我", direct_call=True))
    successor = service.begin_candidate(service.select_decision(service.snapshot("1")))
    assert successor is not None
    service.observe(GroupEvent("1", "bot-old", "99", "旧回答", is_bot=True))
    old_transport.on_sent({"message_id": "bot-old"}, "旧回答")
    state = service.window.get("1")
    assert state.candidate == successor
    assert state.pending_target.message_id == "new"
    assert state.lease_user_id is None


@pytest.mark.asyncio
async def test_context_reader_refreshes_after_admission_and_respects_group_boundary():
    workflow, service = setup_workflow()
    service.observe(GroupEvent("1", "a", "7", "mako 你好"))
    incoming = await workflow.participation.prepare(request("a"), SimpleNamespace())
    service.observe(GroupEvent("1", "b", "8", "刚刚补充的信息"))
    service.observe(GroupEvent("2", "c", "9", "另一个群的内容"))
    assert "刚刚补充的信息" not in incoming.group_context
    refreshed = incoming.read_group_context()
    assert "刚刚补充的信息" in refreshed
    assert "另一个群的内容" not in refreshed


@pytest.mark.asyncio
async def test_sent_reply_text_enters_only_its_group_context():
    workflow, service = setup_workflow()
    service.observe(GroupEvent("1", "a", "7", "mako 你好"))
    transport = SimpleNamespace()
    incoming = await workflow.participation.prepare(request("a"), transport)
    transport.on_sent({"message_id": "bot-reply"}, "已经回答的内容")
    assert "已经回答的内容" in incoming.read_group_context()
    assert "已经回答的内容" not in service.snapshot("2").render()
    event = service.snapshot("1").events[-1]
    assert event.is_bot and event.reply_to_message_id == "a"


@pytest.mark.asyncio
@pytest.mark.parametrize("echo_first", [False, True])
async def test_self_echo_and_confirmation_preserve_single_reply_and_lease(echo_first):
    workflow, service = setup_workflow()
    now = [10.0]
    service.clock = lambda: now[0]
    service.observe(GroupEvent("1", "a", "7", "mako 你好"))
    transport = SimpleNamespace()
    await workflow.participation.prepare(request("a"), transport)
    echo = GroupEvent("1", "bot-reply", "99", "回答", is_bot=True,
                      reply_to_message_id="a", reply_to_user_id="7")
    if echo_first:
        now[0] = 15.0
        service.observe(echo)
    now[0] = 20.0
    transport.on_sent({"message_id": "bot-reply"}, "回答")
    before = service.snapshot("1")
    if not echo_first:
        now[0] = 30.0
        service.observe(echo)
    now[0] = 31.0
    transport.on_sent({"message_id": "bot-reply"}, "回答")
    after = service.snapshot("1")
    assert sum(event.message_id == "bot-reply" for event in after.events) == 1
    assert after.lease_user_id == "7"
    assert after.lease_until == before.lease_until
    assert service.window.get("1").candidate is None


@pytest.mark.asyncio
async def test_late_ack_after_ambient_input_does_not_renew_sticky_candidate():
    workflow, service = setup_workflow()
    service.observe(GroupEvent("1", "a", "7", "mako 你好"))
    transport = SimpleNamespace()
    await workflow.participation.prepare(request("a"), transport)
    original = service.window.get("1").candidate
    service.observe(GroupEvent("1", "bot-reply", "99", "回答", is_bot=True))
    service.observe(GroupEvent("1", "b", "8", "普通补充信息"))
    assert service.window.get("1").candidate == original
    transport.on_sent({"message_id": "bot-reply"}, "回答")
    state = service.window.get("1")
    assert state.candidate == original
    assert state.lease_user_id is None
    assert state.sent_message_id is None


@pytest.mark.asyncio
async def test_send_guard_cannot_refresh_stale_body_token():
    workflow, service = setup_workflow()
    service.observe(GroupEvent("1", "a", "7", "mako 你好"))
    transport = SimpleNamespace()
    incoming = await workflow.participation.prepare(request("a"), transport)
    service.observe(GroupEvent("1", "supplement", "8", "补充信息"))
    assert not incoming.is_current()
    assert not transport.guard()
    # Explicitly refresh only before constructing a new generation request.
    assert incoming.refresh_before_generation()
    assert "补充信息" in incoming.read_group_context()
    assert transport.guard()


@pytest.mark.asyncio
@pytest.mark.parametrize("direct", [False, True])
async def test_tool_classification_precedes_debounce_but_not_group_admission(monkeypatch, direct):
    from src.services.chat.pipeline import participation

    workflow, service = setup_workflow()
    service.debounce_seconds = 1
    service.max_wait_seconds = 2
    text = "翻译 hello"
    workflow.participation.observe("99", GroupEvent("1", "a", "7", text, direct_call=direct))
    sleep = AsyncMock(side_effect=AssertionError("tool must not enter disposable debounce"))
    monkeypatch.setattr(participation, "asyncio", SimpleNamespace(sleep=sleep))
    transport = SimpleNamespace(notice=AsyncMock())
    prepared = await workflow.participation.prepare(request("a", text), transport)
    sleep.assert_not_awaited()
    if direct:
        assert prepared is not None
        assert prepared.is_current is None
        assert transport.category == "command"
        assert service.window.get("1").candidate is None
    else:
        assert prepared is None
