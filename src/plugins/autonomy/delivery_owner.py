"""Owner-only reconciliation for the independent background delivery ledger."""
from __future__ import annotations

import asyncio
import re

from nonebot.adapters.onebot.v11 import PrivateMessageEvent

from src.services.delivery.dispatcher import send_to_event
from src.services.delivery.state import DeliveryStore, DeliveryUnavailable
from src.services.delivery.state.listing import list_delivery_page
from src.services.delivery.state.legacy import list_old_followups, list_retained_reminders
from .effect_feedback import effect_feedback
from .generation_owner import generation_feedback
from .history_owner import history_feedback


def delivery_command(text):
    match = re.fullmatch(r"聊天历史核对\s+([0-9a-f]{64})\s+(已送达|放弃)", text.strip())
    if match:
        return ("history_sent" if match[2] == "已送达" else "history_abandoned"), match[1]
    match = re.fullmatch(r"聊天历史状态\s+([0-9a-f]{64})", text.strip())
    if match:
        return "history_inspect", match[1]
    match = re.fullmatch(r"聊天历史列表(?:\s+([0-9]{1,20}:[0-9]{1,8}))?", text.strip())
    if match:
        return "history_list", match[1] or "0:0"
    match = re.fullmatch(r"生成状态\s+([0-9a-f]{64})", text.strip())
    if match:
        return "generation_inspect", match[1]
    match = re.fullmatch(r"生成列表(?:\s+([0-9]{1,20}:[0-9]{1,8}))?", text.strip())
    if match:
        return "generation_list", match[1] or "0:0"
    match = re.fullmatch(r"(旧跟进列表|提醒待核对)(?:\s+([0-9]{1,20}:[0-9]{1,8}))?", text.strip())
    if match:
        return ("old_followups" if match[1] == "旧跟进列表" else "old_reminders"), match[2] or "0:0"
    match = re.fullmatch(r"发送列表(?:\s+([0-9]{1,20}:[0-9]{1,8}))?", text.strip())
    if match:
        return "list", match[1] or "0:0"
    match = re.fullmatch(r"发送状态\s+([0-9a-f]{64})", text.strip())
    if match:
        return "inspect", match[1]
    match = re.fullmatch(r"发送核对\s+([0-9a-f]{64})\s+(已送达|放弃)", text.strip())
    if match:
        return ("sent" if match[2] == "已送达" else "cancelled"), match[1]
    return None


async def process_delivery_command(ctx, matcher, event, text):
    if (not isinstance(event, PrivateMessageEvent)
            or ctx.settings.autonomy_owner_id is None
            or event.user_id != ctx.settings.autonomy_owner_id):
        return False
    command = delivery_command(text)
    if command is None:
        return False
    operation, action_id = command
    try:
        client = await asyncio.to_thread(lambda: ctx.repository.redis_client)
        store = DeliveryStore(client)
        if operation in {"history_inspect", "history_list", "history_sent", "history_abandoned"}:
            feedback = await asyncio.to_thread(history_feedback, client, operation, action_id, str(event.user_id))
        elif operation in {"generation_inspect", "generation_list"}:
            feedback = await asyncio.to_thread(generation_feedback, client, operation, action_id)
        elif operation in {"old_followups", "old_reminders"}:
            followups = operation == "old_followups"
            reader = list_old_followups if followups else list_retained_reminders
            label = "旧跟进列表" if followups else "提醒待核对"
            page = await asyncio.to_thread(reader, client, action_id)
            lines = [f"{entry.business_id} {entry.status} {entry.target} {entry.due_at}" for entry in page.entries]
            feedback = label + "（本页）：\n" + ("\n".join(lines) if lines else "本页没有待核对项。")
            feedback += (f"\n继续：{label} {page.next_cursor}" if page.next_cursor is not None else "\n本轮扫描结束。")
            feedback += "\n缺少旧发送证据不等于未发送；仅列出记录，未改状态或补发。"
        elif operation == "list":
            page = await asyncio.to_thread(list_delivery_page, client, action_id)
            lines = [f"{entry.action_id} {entry.state} {entry.kind} {entry.target}" for entry in page.entries]
            feedback = "发送记录（本页）：\n" + ("\n".join(lines) if lines else "本页没有可显示的执行记录。")
            feedback += (f"\n继续：发送列表 {page.next_cursor}" if page.next_cursor is not None
                         else "\n本轮扫描结束。")
            feedback += "\n列表不是固定快照；状态未确认项请按ID查询。未触发重发。"
        elif operation == "inspect":
            result = await asyncio.to_thread(store.inspect, action_id)
            feedback = f"发送 {action_id}：{result.state or '没有执行记录'}。"
            if result.spec is not None:
                spec = result.spec
                feedback += f" 类型={spec.kind}，目标={spec.target_type}:{spec.target_id}，版本={spec.revision}。"
            feedback += " 这是执行状态；已送达不表示后续补记全部完成。"
            if result.state == "sent":
                feedback += await asyncio.to_thread(effect_feedback, client, action_id)
        else:
            result = await asyncio.to_thread(store.reconcile, action_id,
                delivered=operation == "sent", operator_id=str(event.user_id))
            feedback = (f"发送 {action_id} 已按人工核对记为 {result.state}；未触发重发。"
                        if result.ok else f"发送 {action_id} 当前为 {result.state or result.code}，未更改。")
            if result.ok and operation == "cancelled":
                feedback += " 放弃后续处理不代表此前没有送达。"
            elif result.ok and operation == "sent":
                feedback += " 实际送达时间未提供；历史、去重冷却和资讯指纹补记保留待核对，不使用核对时间代替。"
    except (DeliveryUnavailable, ValueError):
        feedback = "发送状态暂不可用，本次核对结果未确认；未触发重发。"
    await send_to_event(matcher, event, feedback)
    return True
