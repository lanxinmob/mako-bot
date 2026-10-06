"""Load the transport helper without registering the chat plugin."""
import importlib.util
import asyncio
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from src.services.delivery.dispatcher import OutboundDispatcher


@pytest.mark.asyncio
@pytest.mark.parametrize("render_fails", [False, True])
async def test_failed_send_is_never_retried_as_render_fallback(render_fails):
    path = Path(__file__).resolve().parents[2] / "src/plugins/chat/delivery.py"
    spec = importlib.util.spec_from_file_location("isolated_chat_delivery", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.dispatch = OutboundDispatcher(spacing=0).dispatch
    matcher = SimpleNamespace(send=AsyncMock(side_effect=OSError("unknown send result")))
    bot = SimpleNamespace(get_group_member_list=AsyncMock(return_value=[]))
    if render_fails:
        bot.get_group_member_list.side_effect = OSError("member list unavailable")
    event = GroupMessageEvent.model_construct(group_id=11, user_id=12, message_id=13)
    assert await module.send_reply(matcher, event, bot, "fixture") is False
    matcher.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_guard_rejects_before_transport_send():
    path = Path(__file__).resolve().parents[2] / "src/plugins/chat/delivery.py"
    spec = importlib.util.spec_from_file_location("isolated_chat_delivery", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.dispatch = OutboundDispatcher(spacing=0).dispatch
    matcher = SimpleNamespace(send=AsyncMock())
    bot = SimpleNamespace(get_group_member_list=AsyncMock(return_value=[]))
    event = GroupMessageEvent.model_construct(group_id=11, user_id=12, message_id=13)
    assert await module.send_reply(matcher, event, bot, "fixture", guard=lambda: False) is False
    matcher.send.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("result,acknowledged", [
    (False, False), (None, False), ({}, False), ({"message_id": None}, False),
    ({"message_id": 42}, True), (True, True),
])
@pytest.mark.parametrize("group", [True, False])
async def test_only_acknowledged_text_is_observed(result, acknowledged, group):
    path = Path(__file__).resolve().parents[2] / "src/plugins/chat/delivery.py"
    spec = importlib.util.spec_from_file_location("observed_chat_delivery", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.dispatch = OutboundDispatcher(spacing=0).dispatch
    matcher = SimpleNamespace(send=AsyncMock(return_value=result))
    bot = SimpleNamespace(get_group_member_list=AsyncMock(return_value=[]))
    event = (GroupMessageEvent.model_construct(group_id=11, user_id=12, message_id=13)
             if group else SimpleNamespace(user_id=12))
    observed = Mock()
    assert await module.send_reply(matcher, event, bot, "实际回复", on_sent=observed) is acknowledged
    matcher.send.assert_awaited_once()
    if not acknowledged or not group:
        observed.assert_not_called()
    else:
        observed.assert_called_once_with(result, "实际回复")


@pytest.mark.asyncio
async def test_queued_reply_rechecks_frozen_group_candidate():
    from test.chat.group.test_pipeline import setup_workflow, request
    from src.services.chat.group.models import GroupEvent

    path = Path(__file__).resolve().parents[2] / "src/plugins/chat/delivery.py"
    spec = importlib.util.spec_from_file_location("queued_chat_delivery", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    dispatcher = OutboundDispatcher(spacing=0)
    occupied, release, queued = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def hold():
        occupied.set()
        await release.wait()
        return {"message_id": 1}

    async def enqueue(*args, **kwargs):
        queued.set()
        return await dispatcher.dispatch(*args, **kwargs)

    module.dispatch = enqueue
    workflow, service = setup_workflow()
    service.observe(GroupEvent("1", "a", "7", "mako 你好"))
    transport = SimpleNamespace()
    await workflow.participation.prepare(request("a"), transport)
    matcher = SimpleNamespace(send=AsyncMock())
    bot = SimpleNamespace(get_group_member_list=AsyncMock(return_value=[]))
    event = GroupMessageEvent.model_construct(group_id=1, user_id=7, message_id=13)
    blocker = asyncio.create_task(dispatcher.dispatch("group", 1, hold, category="command"))
    reply = None
    try:
        await asyncio.wait_for(occupied.wait(), 1)
        reply = asyncio.create_task(module.send_reply(matcher, event, bot, "old body", guard=transport.guard))
        await asyncio.wait_for(queued.wait(), 1)
        assert not reply.done()
        service.observe(GroupEvent("1", "b", "8", "新的补充信息"))
        release.set()
        assert await asyncio.wait_for(reply, 1) is False
        matcher.send.assert_not_awaited()
    finally:
        release.set()
        tasks = [blocker] + ([reply] if reply is not None else [])
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_expired_chat_notice_is_silent_without_suppressing_required_notice(monkeypatch):
    from nonebot.adapters.onebot.v11 import Message
    from src.services.delivery import dispatcher

    # Load the real transport class without registering plugins or jobs.
    path = Path(__file__).resolve().parents[2] / "src/plugins/chat/ingress.py"
    source = ast.parse(path.read_text(encoding="utf-8"))
    transport_node = next(node for node in source.body if isinstance(node, ast.ClassDef)
                          and node.name == "QQChatTransport")
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
                              transport_node], type_ignores=[])
    namespace = {"send_notice": dispatcher.send_notice, "Message": Message}
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
    monkeypatch.setattr(dispatcher, "_configured", True)
    monkeypatch.setattr(dispatcher, "outbound", OutboundDispatcher(spacing=0))
    matcher = SimpleNamespace(send=AsyncMock(return_value={"message_id": 1}))
    event = SimpleNamespace(group_id=1, user_id=7, self_id=99)
    transport = namespace["QQChatTransport"](matcher, event, None)
    transport.guard = lambda: False
    assert await transport.notice("expired failure") is False
    matcher.send.assert_not_awaited()
    # Tool/private/approval callers without a disposable candidate retain delivery.
    transport.guard = None
    assert await transport.notice("required feedback") is True
    matcher.send.assert_awaited_once()
