import asyncio
import importlib
from types import SimpleNamespace
from unittest.mock import Mock

import nonebot
import pytest
from nonebot import on_message
from nonebot.adapters.onebot.v11 import Adapter, Bot, MessageEvent
from src.services.delivery.dispatcher import OutboundDispatcher
from test.features.discoveries.test_access import event
from test.features.discoveries.test_plugin import plugin
from test.memory.ledger.test_records import ledger, isolated_redis, source
from src.services.persistence.ledger import LedgerUnavailable
from src.services.memory.ledger import LedgerService


@pytest.fixture
def runtime(plugin, ledger, monkeypatch):
    loaded = nonebot.get_plugin('chat') or nonebot.load_plugin('src.plugins.chat')
    assert loaded
    module = importlib.import_module('src.plugins.chat.ledger_commands')
    commands = importlib.import_module('src.plugins.chat.commands')
    state = SimpleNamespace(sends=[], fallback=[], allowed=True, ledger=ledger)
    monkeypatch.setattr(module, 'storage', ledger.storage)
    monkeypatch.setattr(module, 'governance', SimpleNamespace(can_chat=lambda *_: SimpleNamespace(allowed=state.allowed)))
    queue = OutboundDispatcher(spacing=0)
    monkeypatch.setattr(module, 'dispatch', queue.dispatch)
    monkeypatch.setattr(module, '_explanations', {})
    async def api(bot, name, **kwargs):
        assert name in {'send_msg', 'send_private_msg', 'send_group_msg'}
        state.sends.append(kwargs)
        return {'message_id': 100 + len(state.sends)}
    monkeypatch.setattr(Bot, 'call_api', api)
    fallback = on_message(priority=40, block=False)
    @fallback.handle()
    async def record_fallback(event: MessageEvent):
        state.fallback.append(event.message_id)
    monkeypatch.setattr(importlib.import_module('nonebot.message'), 'matchers',
        {8: [commands.relationship_list_handler, commands.relationship_correct_handler,
             commands.relationship_delete_handler, commands.relationship_explain_handler,
             commands.relationship_relearn_handler, commands.relationship_natural_handler], 40: [fallback]})
    state.bot = Bot(Adapter(nonebot.get_driver()), '42')
    state.module = module
    state.queue = queue
    yield state
    fallback.destroy()


def personal(text, message=81):
    return event(text, private=True).model_copy(update={'user_id': 101, 'message_id': message})


@pytest.mark.asyncio
@pytest.mark.parametrize('loss', ['reserve', 'before_server', 'restart'])
async def test_new_query_recovers_original_pending_intent_without_resend(runtime, loss, monkeypatch):
    ledger = runtime.ledger
    mid = (await ledger.mutate(101, 'auto', None, '我喜欢乌龙茶', source(1)))['memory_id']
    client = ledger.storage.redis
    class LostResponse:
        def __getattr__(self, key):
            return getattr(client, key)
        def eval(self, script, nkeys, *args):
            if loss == 'before_server':
                raise ConnectionError('synthetic request outcome unknown')
            result = client.eval(script, nkeys, *args)
            if args[nkeys] == 'reserve':
                raise ConnectionError('synthetic reservation response lost')
            return result
    ledger.storage.redis = LostResponse()
    with pytest.raises(LedgerUnavailable):
        await ledger.mutate(101, 'forget', mid, '', source(2))
    ledger.storage.redis = client
    if loss == 'restart':
        import src.services.persistence.ledger.repository as module
        monkeypatch.setattr(module, '_uncertain', {})
    # A new message ID is a query, never a new authorization for the lost write.
    await runtime.bot.handle_event(personal('我的记忆', 93))
    assert all(m.status == 'forgotten' and not m.content for m in LedgerService(ledger.storage).list(101))
    assert ledger.repo.state(101)['revision'] == 2
    assert len(runtime.sends) == 1 and '正文已清空' in str(runtime.sends[0]['message'])
    assert not runtime.fallback


@pytest.mark.asyncio
async def test_real_nonebot_self_explain_change_and_forget(runtime):
    ledger = runtime.ledger
    mid = (await ledger.mutate(101, 'auto', None, '我喜欢乌龙茶', source(1)))['memory_id']
    await runtime.bot.handle_event(personal('解释记忆 ' + mid))
    assert '依据：我喜欢乌龙茶' in str(runtime.sends[-1]['message'])
    await runtime.bot.handle_event(personal('以前喜欢乌龙茶，现在不喜欢了', 82))
    assert len([m for m in ledger.list(101) if m.status == 'active']) == 1
    assert any(m.content == '不喜欢：乌龙茶' for m in ledger.list(101))
    await runtime.bot.handle_event(personal('忘掉记忆 ' + mid, 83))
    assert all(m.status == 'forgotten' for m in ledger.list(101))
    assert '历史聊天仍保留' in str(runtime.sends[-1]['message'])
    assert not runtime.fallback
    assert all(all(segment.type == 'text' for segment in message['message']) for message in runtime.sends)


@pytest.mark.asyncio
async def test_group_redirect_before_any_personal_lookup(runtime, monkeypatch):
    monkeypatch.setattr(runtime.module, 'governance', SimpleNamespace(can_chat=Mock(side_effect=AssertionError('read forbidden'))))
    monkeypatch.setattr(runtime.module, 'LedgerService', Mock(side_effect=AssertionError('ledger forbidden')))
    await runtime.bot.handle_event(event('我的记忆'))
    assert len(runtime.sends) == 1 and '本人私聊' in str(runtime.sends[0]['message'])


@pytest.mark.asyncio
async def test_unaccepted_private_is_silent_without_ledger_reads(runtime, monkeypatch):
    runtime.allowed = False
    reader = Mock(side_effect=AssertionError('ledger forbidden'))
    monkeypatch.setattr(runtime.module, 'LedgerService', reader)
    await runtime.bot.handle_event(personal('我的记忆'))
    reader.assert_not_called()
    assert not runtime.sends and not runtime.fallback


@pytest.mark.asyncio
async def test_quote_is_bot_and_user_scoped_and_expires(runtime, monkeypatch):
    ledger = runtime.ledger
    mid = (await ledger.mutate(101, 'auto', None, '我喜欢乌龙茶', source(1)))['memory_id']
    await runtime.bot.handle_event(personal('解释记忆 ' + mid))
    explanation = 101
    quoted = personal('忘掉这件事', 82).model_copy(update={'reply': SimpleNamespace(message_id=explanation)})
    # Same reply ID from another user cannot select this person's explanation.
    await runtime.bot.handle_event(quoted.model_copy(update={'user_id': 102}))
    assert any(m.status == 'active' for m in ledger.list(101))
    key = ('42', 101, str(explanation))
    runtime.module._explanations[key] = (mid, -1000)
    await runtime.bot.handle_event(quoted)
    assert any(m.status == 'active' for m in ledger.list(101))
    await runtime.bot.handle_event(personal('解释记忆 ' + mid, 83))
    latest = 100 + len(runtime.sends)
    quoted = personal('忘掉这件事', 84).model_copy(update={'reply': SimpleNamespace(message_id=latest)})
    await runtime.bot.handle_event(quoted)
    assert all(m.status == 'forgotten' for m in ledger.list(101))


@pytest.mark.asyncio
async def test_access_revoked_while_explanation_queued(runtime):
    mid = (await runtime.ledger.mutate(101, 'auto', None, '我喜欢乌龙茶', source(1)))['memory_id']
    entered, release = asyncio.Event(), asyncio.Event()
    async def occupy():
        entered.set()
        await release.wait()
        return True
    blocking = asyncio.create_task(runtime.queue.dispatch('private', 101, occupy, category='command'))
    await entered.wait()
    task = asyncio.create_task(runtime.bot.handle_event(personal('解释记忆 ' + mid)))
    for _ in range(10):
        await asyncio.sleep(0)
    runtime.allowed = False
    release.set()
    await asyncio.gather(blocking, task)
    assert not runtime.sends
