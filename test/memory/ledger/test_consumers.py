import asyncio
import json
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from src.models.schemas import ChatRecord
from src.services.chat.models import ChatReply
from src.services.chat.pipeline import execution
from src.services.memory.ledger import LedgerService
from src.services.memory.ledger.runtime import for_storage
from src.services.memory.mako_context import MakoRuntimeContext
from src.services.chat.messages import MessageBuilder
from src.services.memory.knowledge_precipitation import KnowledgePrecipitationService
from src.services.delivery.followups import FollowupDelivery
from test.memory.ledger.test_records import ledger, isolated_redis, source
from test.chat.history_delivery.test_runtime_integration import setup_runtime
from test.autonomy.test_execution import scene
from src.services.chat.group.models import GroupEvent, GroupSnapshot


@pytest.mark.asyncio
async def test_real_pipeline_cancels_generation_when_memory_version_changes(setup_runtime, ledger):
    client, services, incoming, transport, tools, matcher = setup_runtime
    # Both fixtures share this test's isolated Redis.
    services.storage = ledger.storage
    services.history_delivery.storage = ledger.storage
    mid = (await ledger.mutate(101, 'auto', None, '我喜欢乌龙茶', source(1)))['memory_id']
    incoming = replace(incoming, address=replace(incoming.address, user_id=101))
    async def generation(request):
        await ledger.mutate(101, 'forget', mid, '', source(2))
        return ChatReply('旧正文乌龙茶', request.history, 'synthetic')
    services.chat_engine.generate.side_effect = generation
    await execution.execute(services, incoming, transport, tools, None)
    matcher.send.assert_not_awaited()
    assert not client.keys('mako:chat:delivery:v1:*')


@pytest.mark.asyncio
async def test_real_pipeline_filters_before_context_builder_and_preserves_audit_history(setup_runtime, ledger):
    client, services, incoming, transport, tools, matcher = setup_runtime
    services.storage = ledger.storage
    services.history_delivery.storage = ledger.storage
    mid = (await ledger.mutate(101, 'auto', None, '我喜欢乌龙茶', source(1)))['memory_id']
    await ledger.mutate(101, 'forget', mid, '', source(2))
    incoming = replace(incoming, address=replace(incoming.address, user_id=101))
    captured = []
    async def generation(request):
        captured.extend(MessageBuilder(ledger.storage, Mock(), MakoRuntimeContext(ledger.storage)).build(replace(request, reply_plan=None)))
        assert request.history == [{'role': 'user', 'content': 'old'}]
        return ChatReply('new reply', request.history + [{'role': 'user', 'content': 'hello'},
                         {'role': 'assistant', 'content': 'new reply'}], 'synthetic')
    services.chat_engine.generate.side_effect = generation
    await execution.execute(services, incoming, transport, tools, None)
    assert services.context_builder.build.call_args.kwargs['history'] == []
    assert 'old' not in str(captured) and '乌龙茶' not in str(captured)
    assert json.loads(client.get('chat:history:group_8'))[0]['content'] == 'old'
    matcher.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_daily_late_result_cannot_write_forgotten_information(ledger, monkeypatch):
    import src.services.memory.knowledge_precipitation as module
    mid = (await ledger.mutate(101, 'auto', None, '我喜欢乌龙茶', source(1)))['memory_id']
    records = [ChatRecord(role='user', user_id=101, content='旧材料乌龙茶')]
    monkeypatch.setattr(ledger.storage, 'get_recent_global_records', lambda _hours: records)
    monkeypatch.setattr(module, 'has_deepseek', lambda: True)
    vector = Mock()
    service = KnowledgePrecipitationService(ledger.storage, vector,
                 image_archive=SimpleNamespace(root=Path('nonexistent-synthetic-images')))
    async def late(_batch):
        await ledger.mutate(101, 'forget', mid, '', source(2))
        return ['过期知识乌龙茶']
    service._extract_knowledge = late
    service._update_profile = AsyncMock(return_value=True)
    result = await service.run()
    assert result.skipped_reason == 'memory version changed'
    vector.add.assert_not_called()
    service._update_profile.assert_not_awaited()
    service._extract_knowledge = AsyncMock(return_value=['旧材料'])
    service._update_profile = KnowledgePrecipitationService._update_profile.__get__(service)
    result = await service.run()
    service._extract_knowledge.assert_not_awaited()
    assert result.profiles_updated == 0


@pytest.mark.asyncio
async def test_pending_followup_stops_at_actual_send_boundary(ledger):
    mid = (await ledger.mutate(101, 'auto', None, '提醒我明天喝水', source(1),
                              due_at=datetime.now() - timedelta(seconds=1)))['memory_id']
    async def schedule(_type, _user, callback, **kwargs):
        await ledger.mutate(101, 'forget', mid, '', source(2))
        return await callback()
    service = FollowupDelivery(ledger.storage.redis, Mock(check=Mock(return_value=SimpleNamespace(allowed=True))),
                               schedule=schedule)
    bot = SimpleNamespace(self_id='999', send_private_msg=AsyncMock(return_value={'message_id': 10}))
    assert not await service.deliver(bot, 101, mid)
    bot.send_private_msg.assert_not_awaited()
    assert all(m.status == 'forgotten' for m in ledger.list(101))


@pytest.mark.asyncio
async def test_daily_profile_result_after_forget_preserves_prior_profile(ledger, monkeypatch):
    import src.services.memory.knowledge_precipitation as module
    mid = (await ledger.mutate(101, 'auto', None, '我喜欢乌龙茶', source(1)))['memory_id']
    ledger.storage.set_profile(101, '合成人物', '旧档案，仅供历史核对')
    async def late(**kwargs):
        await ledger.mutate(101, 'forget', mid, '', source(2))
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='过期画像乌龙茶'))])
    monkeypatch.setattr(module, 'get_deepseek_client', lambda: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=late))))
    monkeypatch.setattr(module, 'memory_model_content', AsyncMock(return_value='合成画像输入'))
    service = KnowledgePrecipitationService(ledger.storage, Mock(), image_archive=Mock())
    assert not await service._update_profile(101, [ChatRecord(role='user', user_id=101, content='旧发言')])
    assert ledger.storage.get_profile(101)['profile_text'] == '旧档案，仅供历史核对'


@pytest.mark.asyncio
@pytest.mark.parametrize('target', ['private', 'group'])
async def test_autonomy_rechecks_after_approval_begin_await(scene, ledger, target):
    from src.services.autonomy.execution import send_action
    ctx, bot = scene
    ctx.storage = ledger.storage
    mid = (await ledger.mutate(101, 'auto', None, '我喜欢乌龙茶', source(1)))['memory_id']
    versions = dict(for_storage(ledger.storage, [101]).stamp)
    async def begin(_text):
        await ledger.mutate(101, 'forget', mid, '', source(2))
        return True
    attempt = SimpleNamespace(begin=begin, acknowledged=False)
    assert not await send_action(ctx, bot, target, 101, '旧候选乌龙茶', '合成原因',
                                 approval_attempt=attempt, memory_versions=versions)
    bot.send_private_msg.assert_not_awaited()
    bot.send_group_msg.assert_not_awaited()
    assert not attempt.acknowledged
    ctx.repository.set_cooldown.assert_not_called()


@pytest.mark.asyncio
async def test_new_controlled_group_participant_cancels_enriched_request(setup_runtime, ledger):
    _, services, incoming, transport, tools, matcher = setup_runtime
    services.storage = ledger.storage
    services.history_delivery.storage = ledger.storage
    mid = (await ledger.mutate(102, 'auto', None, '我喜欢乌龙茶', source(1, user=102)))['memory_id']
    await ledger.mutate(102, 'forget', mid, '', source(2, user=102))
    snapshots = iter([
        GroupSnapshot('8', 0, 0, (GroupEvent('8', '1', '101', text='当前输入'),)),
        GroupSnapshot('8', 0, 0, (GroupEvent('8', '2', '102', text='新参与者'),))])
    incoming = replace(incoming, address=replace(incoming.address, user_id=101),
                       read_group_snapshot=lambda: next(snapshots))
    await execution.execute(services, incoming, transport, tools, None)
    services.chat_engine.generate.assert_not_awaited()
    matcher.send.assert_not_awaited()
