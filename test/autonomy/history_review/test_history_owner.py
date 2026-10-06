import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from nonebot.adapters.onebot.v11 import GroupMessageEvent, PrivateMessageEvent
import pytest

from src.services.chat.history_delivery.worker import HistoryWorker
from test.autonomy.owner_loader import load_owner
from test.autonomy.test_pending_atomic import isolated_redis
from test.persistence.history_commit.test_delivery import planned
from test.persistence.history_commit.test_tasks import acknowledged


def dumps(client):
    return {key: client.dump(key) for key in client.keys("*")}


@pytest.mark.asyncio
async def test_actual_owner_query_lists_independent_results_without_private_payload(acknowledged):
    client, delivery, plan, store = acknowledged
    client.set("chat:history:group_8", '[{"role":"user","content":"private-new-body"}]')
    await HistoryWorker(client).run_action(plan.action_id)
    before = dumps(client)
    owner = load_owner()
    adapter = owner.process_delivery_command.__globals__
    sender = AsyncMock(return_value=True)
    original = adapter["send_to_event"]
    adapter["send_to_event"] = sender
    ctx = SimpleNamespace(settings=SimpleNamespace(autonomy_owner_id=7),
                          repository=SimpleNamespace(redis_client=client),
                          policy=SimpleNamespace(is_enabled=lambda: False))
    event = PrivateMessageEvent.model_construct(user_id=7)
    try:
        assert await owner.process_delivery_command(ctx, object(), event, "聊天历史状态 " + plan.action_id)
        feedback = sender.call_args.args[2]
        assert "会话基线已改变" in feedback and "全局历史=已完成" in feedback
        assert "private-new-body" not in feedback and "reply" not in feedback
        assert json.loads(client.get(delivery.key(plan.action_id)))["token"] not in feedback
        assert await owner.process_delivery_command(ctx, object(), event, "聊天历史列表")
        assert plan.action_id in sender.call_args.args[2]
        assert dumps(client) == before
    finally:
        adapter["send_to_event"] = original


@pytest.mark.asyncio
async def test_history_query_gate_and_bad_record_are_read_only(planned):
    client, delivery, plan = planned
    delivery.create(plan)
    owner = load_owner()
    ctx = SimpleNamespace(settings=SimpleNamespace(autonomy_owner_id=7),
                          repository=SimpleNamespace(redis_client=client))
    sender = AsyncMock(return_value=True)
    adapter = owner.process_delivery_command.__globals__
    original = adapter["send_to_event"]
    adapter["send_to_event"] = sender
    text = "聊天历史状态 " + plan.action_id
    try:
        assert not await owner.process_delivery_command(ctx, object(), PrivateMessageEvent.model_construct(user_id=8), text)
        assert not await owner.process_delivery_command(ctx, object(), GroupMessageEvent.model_construct(user_id=7), text)
        sender.assert_not_awaited()
        key = delivery.key(plan.action_id)
        client.set(key, "invalid-json")
        before = dumps(client)
        assert await owner.process_delivery_command(ctx, object(), PrivateMessageEvent.model_construct(user_id=7), text)
        assert "记录需人工核对" in sender.call_args.args[2]
        assert dumps(client) == before
    finally:
        adapter["send_to_event"] = original
