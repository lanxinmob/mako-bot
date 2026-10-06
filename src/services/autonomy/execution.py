from __future__ import annotations
import uuid
import asyncio
from dataclasses import asdict
from datetime import datetime
from typing import Any
from nonebot.log import logger
from src.models.schemas import ChatRecord
from src.services.delivery.dedup import align_time_greeting
from src.services.delivery.dedup import canonical_intent
from src.services.delivery.dispatcher import dispatch, send_to_private, acknowledged_result
from src.services.delivery.observation import observe_group_output
from .models import AutonomyDecision, PendingAction, TargetType
from .approval import ApprovalUnavailable
from .repository import PendingConflict

async def ask_owner(ctx, bot: Any, decision: AutonomyDecision) -> bool:
    if not decision.target_id or not ctx.policy.target_allowed(decision.target_type, decision.target_id):
        ctx.repository.append_log("ask_owner_rejected", {"reason": "target not allowed", "decision": asdict(decision)})
        return False
    pending = PendingAction(
        pending_id=uuid.uuid4().hex,
        target_type=decision.target_type,
        target_id=decision.target_id,
        message=decision.message,
        reason=decision.reason,
        created_at=ctx.clock(),
        intent=decision.intent,
    )
    try:
        persisted = await asyncio.to_thread(ctx.repository.save_pending, pending)
    except PendingConflict:
        await send_to_private(bot, ctx.settings.autonomy_owner_id,
                              "行动编号冲突，未覆盖已有待办；本次未发送。")
        return False
    if persisted is False:
        await send_to_private(bot, ctx.settings.autonomy_owner_id,
                              f"行动 {pending.pending_id} 的持久化未确认，审批已暂停；本次未发送。")
        return False
    ctx.repository.append_progress_event(
        "owner_confirmation_requested",
        "自主行动需要 owner 确认，已创建待确认项。",
        {"pending": asdict(pending)},
    )
    scene = "群聊" if pending.target_type == "group" else "私聊"
    acknowledged = await send_to_private(
        bot, ctx.settings.autonomy_owner_id,
        message=(
            f"茉子有点拿不准，要不要发到{scene} {pending.target_id}？\n"
            f"候选内容：{pending.message}\n"
            f"原因：{pending.reason}\n"
            f"行动 ID：{pending.pending_id}\n"
            "回复“批准”“取消”或“改成 xxx”就好。"
        ),
    )
    ctx.repository.append_log("ask_owner" if acknowledged else "ask_owner_unacknowledged",
                              {"pending": asdict(pending)})
    return acknowledged


async def ask_owner_clarification(ctx, bot: Any, text: str, decision: AutonomyDecision) -> bool:
    acknowledged = await send_to_private(bot, ctx.settings.autonomy_owner_id, ctx.render_message(text))
    ctx.repository.append_log("ask_owner_clarification" if acknowledged else "clarification_unacknowledged",
                              {"text": text, "decision": asdict(decision)})
    return acknowledged


async def send_action(ctx,
    bot: Any,
    target_type: TargetType,
    target_id: int,
    message: str,
    reason: str,
    *,
    intent: str = "other",
    owner_approved: bool = False,
    approval_attempt=None,
) -> bool:
    if approval_attempt is None:
        message = align_time_greeting(message)
    if not ctx.policy.target_allowed(target_type, target_id):
        ctx.repository.append_log("send_rejected", {"reason": "target not allowed", "target_type": target_type, "target_id": target_id})
        ctx.repository.append_progress_event(
            "send_rejected",
            "自主行动发送被拒绝：目标不在白名单。",
            {"reason": "target not allowed", "target_type": target_type, "target_id": target_id},
        )
        return False
    if ctx.repository.in_cooldown(target_type, target_id):
        ctx.repository.append_log("send_rejected", {"reason": "cooldown", "target_type": target_type, "target_id": target_id})
        ctx.repository.append_progress_event(
            "send_rejected",
            "自主行动发送被拒绝：目标处于冷却期。",
            {"reason": "cooldown", "target_type": target_type, "target_id": target_id},
        )
        return False
    dedup = ctx.outbound_dedup.check(
        target_type=target_type,
        target_id=target_id,
        intent=intent,
        content=message,
    )
    if not dedup.allowed:
        payload = {
            "reason": "semantic duplicate",
            "target_type": target_type,
            "target_id": target_id,
            "intent": canonical_intent(intent, message),
            "similarity": dedup.similarity,
            "matched_message_id": dedup.matched_message_id,
        }
        ctx.repository.append_log("send_rejected", payload)
        ctx.repository.append_progress_event(
            "send_rejected",
            f"自主行动发送被拒绝：{ctx.settings.outbound_dedup_hours} 小时内存在相似表达。",
            payload,
        )
        return False
    access = ctx.governance.can_chat(
        ctx.settings.autonomy_owner_id if target_type == "group" else target_id,
        target_id if target_type == "group" else None,
    )
    if not access.allowed:
        ctx.repository.append_log("send_rejected", {"reason": access.reason, "target_type": target_type, "target_id": target_id})
        return False
    cost = ctx.governance.estimate_llm_cost(len(message), 0)
    budget = ctx.governance.can_consume_cost(ctx.settings.autonomy_owner_id, cost)
    if not budget.allowed:
        ctx.repository.append_log("send_rejected", {"reason": budget.reason, "target_type": target_type, "target_id": target_id})
        return False
    if target_type not in {"group", "private"}:
        return False

    def still_allowed():
        return (
            ctx.policy.target_allowed(target_type, target_id)
            and not ctx.repository.in_cooldown(target_type, target_id)
            and ctx.outbound_dedup.check(target_type=target_type, target_id=target_id,
                                         intent=intent, content=message).allowed
            and ctx.governance.can_chat(
                ctx.settings.autonomy_owner_id if target_type == "group" else target_id,
                target_id if target_type == "group" else None,
            ).allowed
            and ctx.governance.can_consume_cost(ctx.settings.autonomy_owner_id, cost).allowed
        )

    rendered = ctx.render_message(message)

    async def send():
        if approval_attempt is not None and not await approval_attempt.begin(message):
            return False
        if target_type == "group":
            result = await bot.send_group_msg(group_id=target_id, message=rendered)
        else:
            result = await bot.send_private_msg(user_id=target_id, message=rendered)
        acknowledged = acknowledged_result(result)
        if approval_attempt is not None:
            approval_attempt.acknowledged = acknowledged
        if acknowledged and target_type == "group":
            observe_group_output(getattr(bot, "self_id", None), target_id,
                                 result, rendered, "autonomous")
        return acknowledged

    category = "command" if owner_approved else "autonomous"
    if not await dispatch(target_type, target_id, send, category=category, guard=still_allowed):
        ctx.repository.append_log("send_unacknowledged", {
            "target_type": target_type, "target_id": target_id,
            "reason": "dispatch rejected or delivery unconfirmed",
        })
        return False
    _record_sent_action(ctx, target_type, target_id, message, reason, intent, cost)
    return True


async def send_approved(ctx, bot, store, snapshot, replacement=None):
    """Return a truthful Owner response while fencing every approval attempt."""
    from .approval import ApprovalAttempt

    pending = snapshot.pending()
    message = align_time_greeting(replacement or pending.message)
    claim = await asyncio.to_thread(store.claim, snapshot, message)
    if not claim.ok:
        return f"行动 {pending.pending_id} 未再次执行（{claim.state or claim.code}）。"
    attempt = ApprovalAttempt(store, snapshot, claim.token)
    try:
        await send_action(ctx, bot, pending.target_type, pending.target_id, message,
                          pending.reason, intent=pending.intent, owner_approved=True,
                          approval_attempt=attempt)
    finally:
        # Cancellation cannot undo a started Redis operation or external send.
        try:
            saved = await attempt.finish()
        except ApprovalUnavailable:
            saved = False
    if attempt.acknowledged:
        if saved:
            try:
                cleaned = await asyncio.to_thread(store.cleanup, pending.pending_id, claim.token)
            except ApprovalUnavailable:
                return f"行动 {pending.pending_id} 已送达，待办清理未确认；不会重复发送。"
            if not cleaned.ok:
                return f"行动 {pending.pending_id} 已送达，待办清理未确认；不会重复发送。"
            return f"行动 {pending.pending_id} 已送达。"
        return f"行动 {pending.pending_id} 已送达，但状态保存未确认；请勿重复发送。"
    if attempt.boundary_uncertain:
        return f"行动 {pending.pending_id} 发送状态未确认，已暂停重复执行，请核对目标会话。"
    return f"行动 {pending.pending_id} 未进入发送；取消、限频或权限检查阻止了本次执行。"


def _record_sent_action(ctx, target_type, target_id, message, reason, intent, cost):
    """Record independent effects; an acknowledged delivery must never be retried here."""
    states = {}
    operations = (
        ("cooldown", lambda: ctx.repository.set_cooldown(target_type, target_id)),
        ("dedup", lambda: ctx.outbound_dedup.record(
            target_type=target_type, target_id=target_id, intent=intent,
            content=message, source="autonomy")),
        ("cost", lambda: ctx.governance.consume_cost(ctx.settings.autonomy_owner_id, cost)),
        ("history", lambda: ctx.storage.append_global_record(ChatRecord(
            role="assistant", content=message,
            user_id=target_id if target_type == "private" else None,
            group_id=target_id if target_type == "group" else None,
            time=datetime.now(),
        ))),
    )
    for name, operation in operations:
        try:
            operation()
        except Exception:
            # A write may have taken effect before raising. Never retry blindly.
            states[name] = "unknown"
            logger.warning("自主消息已发送，{}补记未确认", name)
        else:
            # Repositories may silently use memory fallback; this is not durability.
            states[name] = "call_completed"
    payload = {"target_type": target_type, "target_id": target_id,
               "reason": reason, "message_preview": message[:160],
               "bookkeeping": states}
    for name, operation in (
        ("log", lambda: ctx.repository.append_log("sent", payload)),
        ("progress", lambda: ctx.repository.append_progress_event(
            "message_sent", "自主行动消息已发送；补记状态分别记录。", payload)),
    ):
        try:
            operation()
        except Exception:
            logger.warning("自主消息已发送，{}审计调用失败", name)
