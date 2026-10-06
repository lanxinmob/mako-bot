"""Autonomous delivery permission, approval and failure boundaries."""
import asyncio
import json
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.services.autonomy.execution import send_action
from src.services.autonomy.models import PendingAction
from test.autonomy.test_pending_atomic import isolated_redis
from test.autonomy.test_approval import approval


@pytest.fixture
def scene(monkeypatch):
    from src.services.autonomy import execution
    from src.services.delivery import dispatcher as delivery_module
    from src.services.delivery.dispatcher import OutboundDispatcher
    dispatcher = OutboundDispatcher(spacing=0)
    monkeypatch.setattr(execution, "dispatch", dispatcher.dispatch)
    monkeypatch.setattr(delivery_module, "dispatch", dispatcher.dispatch)
    ctx = SimpleNamespace(
        settings=SimpleNamespace(autonomy_owner_id=99, outbound_dedup_hours=24),
        policy=Mock(), repository=Mock(), governance=Mock(),
        outbound_dedup=Mock(), storage=Mock(), render_message=lambda text: text,
    )
    ctx.policy.target_allowed.return_value = True
    ctx.repository.in_cooldown.return_value = False
    ctx.outbound_dedup.check.return_value = SimpleNamespace(
        allowed=True, similarity=1.0, matched_message_id="fixture",
    )
    ctx.governance.can_chat.return_value = SimpleNamespace(allowed=True)
    ctx.governance.can_consume_cost.return_value = SimpleNamespace(allowed=True)
    ctx.governance.estimate_llm_cost.return_value = 0.01
    bot = SimpleNamespace(send_group_msg=AsyncMock(return_value={"message_id": 1}),
                          send_private_msg=AsyncMock(return_value={"message_id": 2}))
    return ctx, bot


def assert_no_success_state(ctx):
    ctx.governance.consume_cost.assert_not_called()
    ctx.repository.set_cooldown.assert_not_called()
    ctx.outbound_dedup.record.assert_not_called()
    ctx.storage.append_global_record.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("denial", ["target", "cooldown", "duplicate", "access", "budget"])
async def test_rejection_cannot_send_or_record_success(scene, denial):
    ctx, bot = scene
    if denial == "target":
        ctx.policy.target_allowed.return_value = False
    elif denial == "cooldown":
        ctx.repository.in_cooldown.return_value = True
    elif denial == "duplicate":
        ctx.outbound_dedup.check.return_value.allowed = False
    elif denial == "access":
        ctx.governance.can_chat.return_value = SimpleNamespace(allowed=False, reason="blocked")
    else:
        ctx.governance.can_consume_cost.return_value = SimpleNamespace(allowed=False, reason="budget")
    assert not await send_action(ctx, bot, "group", 7, "合成测试内容", "fixture")
    bot.send_group_msg.assert_not_awaited()
    bot.send_private_msg.assert_not_awaited()
    assert_no_success_state(ctx)


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["group", "private"])
async def test_sender_failure_leaves_success_state_untouched(scene, target):
    ctx, bot = scene
    sender = bot.send_group_msg if target == "group" else bot.send_private_msg
    sender.side_effect = RuntimeError("synthetic send failure")
    assert not await send_action(ctx, bot, target, 7, "合成测试内容", "fixture")
    assert_no_success_state(ctx)


@pytest.mark.asyncio
async def test_success_is_recorded_after_delivery(scene, monkeypatch):
    ctx, bot = scene
    from src.services.autonomy import execution
    plugin_observer = Mock()
    monkeypatch.setattr(execution, "observe_plugin_output", plugin_observer)
    bot.self_id = "9"

    async def delivered(**kwargs):
        assert kwargs == {"group_id": 7, "message": "合成测试内容"}
        assert_no_success_state(ctx)
        return {"message_id": 1}

    bot.send_group_msg.side_effect = delivered
    assert await send_action(ctx, bot, "group", 7, "合成测试内容", "fixture")
    plugin_observer.assert_called_once_with("9", "group", 7, {"message_id": 1},
                                           "合成测试内容", "autonomous")
    ctx.governance.consume_cost.assert_called_once_with(99, 0.01)
    ctx.repository.set_cooldown.assert_called_once_with("group", 7)
    ctx.outbound_dedup.record.assert_called_once()
    record = ctx.storage.append_global_record.call_args.args[0]
    assert record.group_id == 7 and record.user_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["cooldown", "dedup", "cost", "history", "log", "progress"])
async def test_bookkeeping_failure_does_not_negate_delivery(scene, failure):
    ctx, bot = scene
    operations = {
        "cooldown": ctx.repository.set_cooldown,
        "dedup": ctx.outbound_dedup.record,
        "cost": ctx.governance.consume_cost,
        "history": ctx.storage.append_global_record,
        "log": ctx.repository.append_log,
        "progress": ctx.repository.append_progress_event,
    }
    operations[failure].side_effect = RuntimeError("synthetic partial write")
    assert await send_action(ctx, bot, "group", 7, "合成测试内容", "fixture")
    bot.send_group_msg.assert_awaited_once()
    for operation in operations.values():
        operation.assert_called_once()
    states = ctx.repository.append_progress_event.call_args.args[2]["bookkeeping"]
    assert states == {
        name: "unknown" if name == failure else "call_completed"
        for name in ("cooldown", "dedup", "cost", "history")
    }


@pytest.mark.asyncio
async def test_guard_rechecks_target_after_initial_admission(scene):
    ctx, bot = scene
    ctx.policy.target_allowed.side_effect = [True, False]
    assert not await send_action(ctx, bot, "group", 7, "合成测试内容", "fixture")
    bot.send_group_msg.assert_not_awaited()
    assert_no_success_state(ctx)


@pytest.mark.asyncio
async def test_two_approvals_send_once(scene, approval):
    from src.services.autonomy.execution import send_approved
    ctx, bot = scene
    _, store, snapshot = approval
    entered, release = asyncio.Event(), asyncio.Event()

    async def sending(**kwargs):
        entered.set()
        await release.wait()
        return {"message_id": 1}

    bot.send_group_msg.side_effect = sending
    first = asyncio.create_task(send_approved(ctx, bot, store, snapshot))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        second = await send_approved(ctx, bot, store, snapshot)
        assert "未再次执行" in second
        assert not store.cancel(snapshot).ok
    finally:
        release.set()
        await first
    bot.send_group_msg.assert_awaited_once()
    assert store.inspect("p1").state == "sent"


@pytest.mark.asyncio
async def test_uncertain_delivery_cannot_be_approved_again(scene, approval):
    from src.services.autonomy.execution import send_approved
    ctx, bot = scene
    _, store, snapshot = approval
    bot.send_group_msg.side_effect = TimeoutError("synthetic remote timeout")
    assert "状态未确认" in await send_approved(ctx, bot, store, snapshot)
    assert store.inspect("p1").state == "unknown"
    assert "未再次执行" in await send_approved(ctx, bot, store, snapshot)
    bot.send_group_msg.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["group", "private"])
@pytest.mark.parametrize("result", [None, {}, {"message_id": None}, False])
async def test_missing_receipt_preserves_pending_without_success_effects(scene, approval, target, result):
    from src.services.autonomy.execution import send_approved
    ctx, bot = scene
    client, store, snapshot = approval
    # Match the persisted pending body, not only the in-memory snapshot.
    if target == "private":
        body = json.loads(client.get("autonomy:pending:p1"))
        body["target_type"] = target
        client.set("autonomy:pending:p1", json.dumps(body))
        snapshot = store.load("p1")
    sender = bot.send_group_msg if target == "group" else bot.send_private_msg
    sender.return_value = result
    assert "状态未确认" in await send_approved(ctx, bot, store, snapshot)
    assert store.inspect("p1").state == "unknown"
    assert client.get("autonomy:pending:p1") is not None
    assert_no_success_state(ctx)
    assert "未再次执行" in await send_approved(ctx, bot, store, snapshot)
    sender.assert_awaited_once()


@pytest.mark.asyncio
async def test_sent_state_write_failure_preserves_ack(scene, approval, monkeypatch):
    from src.services.autonomy.execution import send_approved
    from src.services.autonomy.approval import ApprovalUnavailable
    ctx, bot = scene
    _, store, snapshot = approval
    monkeypatch.setattr(store, "mark_sent", Mock(side_effect=ApprovalUnavailable))
    feedback = await send_approved(ctx, bot, store, snapshot)
    assert "已送达，但状态保存未确认" in feedback
    assert store.inspect("p1").state == "sending"
    assert "未再次执行" in await send_approved(ctx, bot, store, snapshot)
    bot.send_group_msg.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("raises", [False, True])
async def test_failed_cleanup_preserves_sent_and_reports_pending_work(scene, approval, monkeypatch, raises):
    from src.services.autonomy.execution import send_approved
    from src.services.autonomy.approval import ApprovalUnavailable
    ctx, bot = scene
    client, store, snapshot = approval
    cleanup = Mock(return_value=SimpleNamespace(ok=False))
    if raises:
        cleanup.side_effect = ApprovalUnavailable
    monkeypatch.setattr(store, "cleanup", cleanup)
    feedback = await send_approved(ctx, bot, store, snapshot)
    assert "已送达，待办清理未确认" in feedback
    assert store.inspect("p1").state == "sent"
    assert client.get("autonomy:pending:p1") is not None
    assert "未再次执行" in await send_approved(ctx, bot, store, snapshot)
    bot.send_group_msg.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["批准", "取消"])
async def test_owner_approval_and_cancel_preserve_pending_lifecycle(scene, command, isolated_redis):
    # Load the real command implementation without registering the QQ plugin.
    from test.autonomy.owner_loader import load_owner
    owner = load_owner()
    ctx, bot = scene
    seconds, micros = isolated_redis.time()
    pending = PendingAction(
        "p1", "group", 7, "合成测试内容", "fixture", seconds + micros / 1e6,
    )
    ctx.settings.autonomy_pending_ttl_seconds = 300
    ctx.repository.redis_client = isolated_redis
    isolated_redis.set("autonomy:pending:p1", json.dumps(asdict(pending)))
    isolated_redis.set("autonomy:pending:latest", "p1")
    matcher = SimpleNamespace(send=AsyncMock())
    # Exhaust unsolicited capacity first: an approved action is still requested work.
    assert await send_action(ctx, bot, "group", 7, "先前自动分享", "fixture")
    bot.send_group_msg.reset_mock()
    ctx.repository.set_cooldown.reset_mock()
    ctx.governance.consume_cost.reset_mock()
    ctx.outbound_dedup.record.reset_mock()
    ctx.storage.append_global_record.reset_mock()
    event = Mock(spec=owner.PrivateMessageEvent, user_id=99)
    assert await owner.process_owner_private(ctx, bot, matcher, event, command)
    assert isolated_redis.get("autonomy:pending:p1") is None
    state = json.loads(isolated_redis.get("autonomy:execution:p1"))["state"]
    assert state == ("sent" if command == "批准" else "cancelled")
    if command == "批准":
        bot.send_group_msg.assert_awaited_once()
        ctx.repository.set_cooldown.assert_called_once_with("group", 7)
    else:
        bot.send_group_msg.assert_not_awaited()
        assert_no_success_state(ctx)
