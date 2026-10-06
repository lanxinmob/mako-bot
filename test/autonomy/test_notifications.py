from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.services.autonomy import execution, workflow
from src.services.autonomy.models import AutonomyDecision


@pytest.mark.asyncio
@pytest.mark.parametrize("delivered", [False, True])
@pytest.mark.parametrize("target", [7, None])
async def test_workflow_only_reports_asked_after_notification_ack(monkeypatch, delivered, target):
    ctx = SimpleNamespace(
        policy=Mock(), repository=Mock(), settings=SimpleNamespace(autonomy_owner_id=99),
        clock=lambda: 1000, render_message=str,
    )
    ctx.policy.target_allowed.return_value = True
    ctx.policy.should_act_directly.return_value = False
    ctx.policy.should_ask_owner.return_value = True
    send = AsyncMock(return_value=delivered)
    monkeypatch.setattr(execution, "send_to_private", send)
    decision = AutonomyDecision("ask_owner", "group", target, .8, "medium", "fixture", "test")
    result = await workflow.handle_decision(ctx, object(), decision)
    assert result == ("asked" if delivered else "notification_failed")
    send.assert_awaited_once()
    assert ctx.repository.save_pending.call_count == int(target is not None)
    ctx.repository.delete_pending.assert_not_called()


@pytest.mark.asyncio
async def test_unpersisted_pending_is_not_reported_ready(monkeypatch):
    ctx = SimpleNamespace(policy=Mock(), repository=Mock(),
                          settings=SimpleNamespace(autonomy_owner_id=99), clock=lambda: 1000)
    ctx.repository.save_pending.return_value = False
    send = AsyncMock(return_value=True)
    monkeypatch.setattr(execution, "send_to_private", send)
    decision = AutonomyDecision("ask_owner", "group", 7, .8, "medium", "fixture", "test")
    assert not await execution.ask_owner(ctx, object(), decision)
    assert "审批已暂停" in send.call_args.args[2]
    ctx.repository.append_progress_event.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("receipt,expected", [
    (None, "notification_failed"), ({}, "notification_failed"),
    ({"message_id": None}, "notification_failed"), (False, "notification_failed"),
    ({"message_id": 123}, "asked"), (True, "asked"),
])
async def test_real_owner_notification_adapter_requires_receipt(monkeypatch, receipt, expected):
    from src.services.delivery import dispatcher
    queue = dispatcher.OutboundDispatcher(spacing=0)
    monkeypatch.setattr(dispatcher, "dispatch", queue.dispatch)
    ctx = SimpleNamespace(
        policy=Mock(), repository=Mock(), settings=SimpleNamespace(autonomy_owner_id=99),
        clock=lambda: 1000, render_message=str,
    )
    ctx.policy.target_allowed.return_value = True
    ctx.policy.should_act_directly.return_value = False
    ctx.policy.should_ask_owner.return_value = True
    bot = SimpleNamespace(send_private_msg=AsyncMock(return_value=receipt))
    decision = AutonomyDecision("ask_owner", "group", 7, .8, "medium", "fixture", "test")
    assert await workflow.handle_decision(ctx, bot, decision) == expected
    bot.send_private_msg.assert_awaited_once()
    ctx.repository.save_pending.assert_called_once()
    ctx.repository.delete_pending.assert_not_called()
    assert ctx.repository.append_log.call_args.args[0] == (
        "ask_owner" if expected == "asked" else "ask_owner_unacknowledged")
