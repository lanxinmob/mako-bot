from __future__ import annotations
import asyncio
from typing import Any
from nonebot.adapters.onebot.v11 import MessageEvent, PrivateMessageEvent
from nonebot.matcher import Matcher
from src.services.autonomy import planning, workflow, execution
from src.services.delivery.dispatcher import send_to_event
from src.services.autonomy.approval import ApprovalStore, ApprovalUnavailable, InvalidPending
from src.services.autonomy.parsing import parse_whitelist_command, approval_command, reconciliation_command
from .delivery_owner import delivery_command, process_delivery_command

def is_owner(ctx, event: MessageEvent) -> bool:
    return ctx.settings.autonomy_owner_id is not None and event.user_id == ctx.settings.autonomy_owner_id


async def autonomy_rule(ctx, event: MessageEvent) -> bool:
    if not isinstance(event, PrivateMessageEvent) or not is_owner(ctx, event):
        return False
    text = event.get_plaintext().strip()
    if reconciliation_command(text) or delivery_command(text):
        return True
    if not ctx.policy.is_enabled():
        return False
    if parse_whitelist_command(text):
        return True
    command = approval_command(text)
    if command:
        return True
    return await planning.is_autonomy_suggestion(ctx, text)


async def process_owner_private(ctx, bot: Any, matcher: Matcher, event: PrivateMessageEvent, text: str) -> bool:
    if not isinstance(event, PrivateMessageEvent) or not is_owner(ctx, event):
        return False
    if await process_delivery_command(ctx, matcher, event, text):
        return True
    reconciliation = reconciliation_command(text)
    if reconciliation:
        operation, pending_id = reconciliation
        client = await asyncio.to_thread(lambda: ctx.repository.redis_client)
        store = ApprovalStore(client,
                              pending_ttl_seconds=ctx.settings.autonomy_pending_ttl_seconds)
        try:
            if operation == "inspect":
                result = await asyncio.to_thread(store.inspect, pending_id)
                feedback = f"行动 {pending_id}：{result.state or '没有执行记录'}。"
            else:
                result = await asyncio.to_thread(store.reconcile, pending_id, delivered=operation == "sent")
                feedback = (f"行动 {pending_id} 已按人工核对记录为 {result.state}；未触发重发。"
                            if result.ok else f"行动 {pending_id} 当前为 {result.state or result.code}，未更改。")
                if operation == "cancelled" and result.ok:
                    feedback += "放弃后续处理不代表此前没有送达。"
        except (ApprovalUnavailable, ValueError):
            feedback = "行动状态暂不可用，未确认本次核对结果。"
        await send_to_event(matcher, event, feedback)
        return True
    if not ctx.policy.is_enabled():
        return False
    whitelist = parse_whitelist_command(text)
    if whitelist:
        label = "群聊" if whitelist.target_type == "group" else "私聊好友"
        if whitelist.action == "list":
            await send_to_event(matcher, event, ctx.policy.format_whitelist(whitelist.target_type))
            return True
        if whitelist.action == "add":
            ctx.repository.add_dynamic_allowlist(whitelist.target_type, whitelist.target_ids)
            await send_to_event(matcher, event,
                f"好，茉子记下啦。已加入{label}白名单：{', '.join(str(item) for item in whitelist.target_ids)}"
            )
            return True
        if whitelist.action == "remove":
            ctx.repository.remove_dynamic_allowlist(whitelist.target_type, whitelist.target_ids)
            await send_to_event(matcher, event,
                f"好，茉子会收着点。已移出{label}白名单：{', '.join(str(item) for item in whitelist.target_ids)}"
            )
            return True

    command = approval_command(text)
    if command:
        action, replacement = command
        client = await asyncio.to_thread(lambda: ctx.repository.redis_client)
        store = ApprovalStore(client,
                              pending_ttl_seconds=ctx.settings.autonomy_pending_ttl_seconds,
                              queued_lease_seconds=180)
        try:
            snapshot = await asyncio.to_thread(store.load_latest)
            if snapshot is None:
                feedback = "没有已持久化的待确认行动；未执行发送。"
            elif action == "cancel":
                result = await asyncio.to_thread(store.cancel, snapshot)
                if result.ok:
                    feedback = f"行动 {snapshot.pending_id} 已取消，尚未进入发送。"
                    try:
                        cleaned = await asyncio.to_thread(store.cleanup, snapshot.pending_id, result.token)
                    except ApprovalUnavailable:
                        cleaned = None
                    if cleaned is None or not cleaned.ok:
                        feedback += "待办清理未确认，但取消状态已保存。"
                else:
                    feedback = f"行动 {snapshot.pending_id} 状态为 {result.state or result.code}，不能保证撤回。"
            else:
                feedback = await execution.send_approved(ctx, bot, store, snapshot, replacement)
        except (ApprovalUnavailable, InvalidPending):
            feedback = "审批状态暂不可用，已暂停本次处理；待办保留，请勿重复发送。"
        await send_to_event(matcher, event, feedback)
        return True

    decision = await planning.decide(ctx, suggestion=text)
    outcome = await workflow.handle_decision(ctx, bot, decision)
    if outcome == "sent":
        await send_to_event(matcher, event, "茉子自己判断可以说，已经发出去啦。")
    elif outcome == "asked":
        await send_to_event(matcher, event, "茉子有点拿不准，已经先私聊你确认啦。")
    elif outcome == "notification_failed":
        await send_to_event(matcher, event, "确认通知未能确认送达，本次没有执行对外行动。")
    elif outcome == "rejected":
        await send_to_event(matcher, event, f"茉子想了想，这次不能行动。原因：{decision.reason}")
    else:
        await send_to_event(matcher, event, f"茉子想了想，这次先不行动。原因：{decision.reason}")
    return True
