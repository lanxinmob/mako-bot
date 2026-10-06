from types import SimpleNamespace
from unittest.mock import AsyncMock

from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, PrivateMessageEvent
import pytest

from src.services.persistence.history_commit.tasks import HistoryEffects
from src.services.chat.history_delivery.discovery import HistoryScanner
from test.autonomy.history_review.test_history_owner import dumps
from test.autonomy.owner_loader import load_owner
from test.autonomy.test_pending_atomic import isolated_redis
from test.persistence.history_commit.test_delivery import planned
from test.persistence.history_commit.test_reconciliation import unknown


@pytest.mark.asyncio
@pytest.mark.parametrize("conclusion", ["已送达", "放弃"])
async def test_manual_history_command_uses_owner_gate_even_when_autonomy_disabled(unknown, conclusion):
    client, delivery, plan, token, store = unknown
    owner = load_owner()
    adapter = owner.process_delivery_command.__globals__
    original = adapter["send_to_event"]
    sender = AsyncMock(return_value=True)
    adapter["send_to_event"] = sender
    ctx = SimpleNamespace(settings=SimpleNamespace(autonomy_owner_id=7),
                          repository=SimpleNamespace(redis_client=client),
                          policy=SimpleNamespace(is_enabled=lambda: False))
    text = f"聊天历史核对 {plan.action_id} {conclusion}"
    event = PrivateMessageEvent.model_construct(user_id=7, message=Message(text))
    try:
        before = dumps(client)
        assert not await owner.process_owner_private(ctx, None, object(),
            PrivateMessageEvent.model_construct(user_id=8), text)
        assert not await owner.process_owner_private(ctx, None, object(),
            GroupMessageEvent.model_construct(user_id=7), text)
        sender.assert_not_awaited()
        assert dumps(client) == before
        assert await owner.autonomy_rule(ctx, event)
        assert await owner.process_owner_private(ctx, None, object(), event, text)
        feedback = sender.call_args.args[2]
        assert "人工核对已保存" in feedback and "未触发补记、重发或模型调用" in feedback
        if conclusion == "已送达":
            assert "实际送达时间未知" in feedback and "不使用核对时间补记" in feedback
            assert feedback.count("待核对；尝试=0") == 2
        else:
            assert "不代表未送达" in feedback
        assert token not in feedback and "reply" not in feedback
        before = dumps(client)
        assert await owner.process_owner_private(ctx, None, object(), event, text)
        assert dumps(client) == before
        assert delivery.transition(plan.action_id, token, "sent", delivered_at_ms=1791240000123) == "denied"
        assert HistoryEffects(client).claim(plan.action_id, "global") is None
        assert dumps(client) == before
    finally:
        adapter["send_to_event"] = original


@pytest.mark.asyncio
async def test_manual_history_unavailable_reports_unconfirmed_without_memory_fallback():
    owner = load_owner()
    adapter = owner.process_delivery_command.__globals__
    original = adapter["send_to_event"]
    sender = AsyncMock(return_value=True)
    adapter["send_to_event"] = sender
    ctx = SimpleNamespace(settings=SimpleNamespace(autonomy_owner_id=7),
                          repository=SimpleNamespace(redis_client=None),
                          policy=SimpleNamespace(is_enabled=lambda: False))
    try:
        assert await owner.process_owner_private(ctx, None, object(),
            PrivateMessageEvent.model_construct(user_id=7), f"聊天历史核对 {'a' * 64} 已送达")
        assert "本次核对结果未确认" in sender.call_args.args[2]
        assert "已保存" not in sender.call_args.args[2]
    finally:
        adapter["send_to_event"] = original


@pytest.mark.asyncio
@pytest.mark.parametrize("delivered", [True, False])
async def test_recovery_scan_keeps_manual_conclusion_without_history_writes(unknown, delivered):
    client, delivery, plan, token, store = unknown
    assert store.reconcile(plan.action_id, delivered=delivered, operator_id="7") in {"sent", "abandoned"}
    before = dumps(client)
    page = await HistoryScanner(client).run_page()
    assert page.outcomes == () and page.visited == 1
    assert dumps(client) == before


def test_manual_confirmation_cannot_end_prepared_or_active_sending(planned):
    from src.services.persistence.history_commit.reconciliation import HistoryReconciliation

    client, delivery, plan = planned
    token = delivery.create(plan)
    store = HistoryReconciliation(client)
    for state in ("prepared", "sending"):
        if state == "sending":
            assert delivery.transition(plan.action_id, token, "begin") == state
        before = dumps(client)
        for delivered in (True, False):
            assert store.reconcile(plan.action_id, delivered=delivered, operator_id="7") == "denied"
            assert dumps(client) == before
