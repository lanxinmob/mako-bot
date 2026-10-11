import asyncio
import importlib.util
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from nonebot.adapters.onebot.v11 import PrivateMessageEvent
from src.services.chat.group.models import GroupEvent, GroupSnapshot
from src.services.chat.models import ChatRequest
from src.services.chat.messages import MessageBuilder
from src.services.memory.mako_context import MakoRuntimeContext
from src.services.memory.ledger.runtime import for_storage, critical
from src.services.memory.ledger.commands import parse, execute as command
from src.services.delivery.dispatcher import OutboundDispatcher
from test.memory.ledger.test_records import ledger, isolated_redis, source, run


def adapter():
    path = Path(__file__).resolve().parents[3] / 'src/plugins/chat/delivery.py'
    spec = importlib.util.spec_from_file_location('ledger_qq_delivery', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.dispatch = OutboundDispatcher(spacing=0).dispatch
    return module


def test_program_filters_sources_preserving_durable_history(ledger):
    mid = run(ledger, 'auto', text='我喜欢乌龙茶')['memory_id']
    ledger.storage.set_profile(101, '合成人物', '旧画像乌龙茶')
    run(ledger, 'forget', mid, message=2)
    view = for_storage(ledger.storage, [101, 102])
    cutoff = view.cutoff_ns
    group = GroupSnapshot('1', 0, 0, (
        GroupEvent('1', '1', '101', text='旧群消息乌龙茶', received_ns=cutoff - 1),
        GroupEvent('1', '2', '102', text='新的群消息', received_ns=cutoff + 1)))
    assert '旧群消息' not in view.group_context(group) and '新的群消息' in view.group_context(group)
    search = Mock(side_effect=AssertionError('unscoped vector must not be read'))
    builder = MessageBuilder(ledger.storage, search, MakoRuntimeContext(ledger.storage))
    old_history = [{'role': 'user', 'content': '旧历史乌龙茶'}]
    request = ChatRequest('private_101', 101, '合成人物', '现在请解释代数', '现在请解释代数', old_history,
                          memory_view=view, plugin_history=[dict(content='旧插件乌龙茶', category='command', sent_at_ms=1)])
    messages = builder.build(request)
    assert '乌龙茶' not in str(messages) and '现在请解释代数' in str(messages)
    assert request.history == old_history  # Audit history was not erased to filter a prompt.
    view.record('b', 's', [{'role': 'assistant', 'content': '新代次'}])
    assert view.history('b', 's', old_history)[0]['content'] == '新代次'
    assert for_storage(ledger.storage, [101]).history('restart', 's', old_history) == []
    search.assert_not_called()


@pytest.mark.asyncio
async def test_actual_transport_rechecks_after_guard_and_persistence_await(ledger):
    mid = (await ledger.mutate(101, 'auto', None, '我喜欢乌龙茶', source(1)))['memory_id']
    view = for_storage(ledger.storage, [101])
    async def before_send():
        await ledger.mutate(101, 'forget', mid, '', source(2))
        return True
    matcher = SimpleNamespace(send=AsyncMock(return_value={'message_id': 30}))
    event = PrivateMessageEvent.model_construct(user_id=101)
    assert not await adapter().send_reply(matcher, event, SimpleNamespace(self_id='999'), '旧正文乌龙茶',
                                         guard=lambda: True, before_send=before_send, memory_view=view)
    matcher.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_explanation_queued_then_forgotten_never_starts_old_body(ledger):
    mid = (await ledger.mutate(101, 'auto', None, '我喜欢乌龙茶', source(1)))['memory_id']
    text, view, _ = await command(ledger, 101, parse('解释记忆 ' + mid), source(2))
    queue = OutboundDispatcher(spacing=0)
    entered, release = asyncio.Event(), asyncio.Event()
    async def occupy():
        entered.set()
        await release.wait()
        return True
    blocking = asyncio.create_task(queue.dispatch('private', 101, occupy, category='command'))
    await entered.wait()
    sender = AsyncMock(return_value={'message_id': 3})
    pending = asyncio.create_task(queue.dispatch('private', 101, lambda: view.send(lambda: sender(text)), category='command'))
    await asyncio.sleep(0)
    await ledger.mutate(101, 'forget', mid, '', source(3))
    release.set()
    await blocking
    assert not await pending
    sender.assert_not_awaited()


@pytest.mark.asyncio
async def test_transport_started_before_control_remains_unknown_not_retried(ledger):
    mid = (await ledger.mutate(101, 'auto', None, '我喜欢乌龙茶', source(1)))['memory_id']
    view = for_storage(ledger.storage, [101])
    entered, release = asyncio.Event(), asyncio.Event()
    async def network():
        entered.set()
        await release.wait()
        raise TimeoutError('synthetic unknown send')
    task = asyncio.create_task(view.send(network))
    await entered.wait()
    await asyncio.wait_for(ledger.mutate(101, 'forget', mid, '', source(2)), 2)
    assert not view.current()  # Gate is not held over network I/O.
    release.set()
    with pytest.raises(TimeoutError):
        await task
    assert all(m.status == 'forgotten' for m in ledger.list(101))


@pytest.mark.asyncio
async def test_competing_corrections_accept_only_original_fixed_version(ledger):
    mid = (await ledger.mutate(101, 'auto', None, '我喜欢乌龙茶', source(1)))['memory_id']
    revision = ledger.repo.state(101)['revision']
    results = await asyncio.gather(*[
        ledger.mutate(101, 'correct', mid, text, source(i), expected_revision=revision)
        for i, text in [(2, '我不喜欢乌龙茶'), (3, '我讨厌乌龙茶')]])
    assert sorted(r['status'] for r in results) == ['conflict', 'correct']
    assert len([m for m in ledger.list(101) if m.status == 'active']) == 1


@pytest.mark.asyncio
async def test_revoked_command_waiting_for_commit_gate_cannot_modify(ledger):
    mid = (await ledger.mutate(101, 'auto', None, '我喜欢乌龙茶', source(1)))['memory_id']
    allowed = True
    async with critical():
        task = asyncio.create_task(command(ledger, 101, parse('忘掉记忆 ' + mid), source(2), admit=lambda: allowed))
        await asyncio.sleep(0)
        allowed = False
    result, _, _ = await task
    assert '未接纳' in result
    assert ledger.list(101)[0].status == 'active'


@pytest.mark.asyncio
async def test_natural_ambiguity_and_cross_topic_keep_state(ledger):
    await ledger.mutate(101, 'auto', None, '我喜欢乌龙茶', source(1))
    await ledger.mutate(101, 'auto', None, '我喜欢红茶', source(2))
    text, _, _ = await command(ledger, 101, parse('以前喜欢，现在不喜欢了'), source(3))
    assert 'ID' in text and len([m for m in ledger.list(101) if m.status == 'active']) == 2
    text, _, _ = await command(ledger, 101, parse('你为什么觉得我喜欢乌龙茶？'), source(4))
    assert '依据：我喜欢乌龙茶' in text
    text, _, _ = await command(ledger, 101, parse('以前喜欢乌龙茶，现在不喜欢了'), dict(source(5), quoted=True))
    assert '引用不作为' in text
