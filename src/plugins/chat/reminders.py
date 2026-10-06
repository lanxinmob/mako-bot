"""OneBot/APScheduler adapter for durable reminder lifecycle operations."""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

from nonebot import get_bot, get_driver
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent
from nonebot.log import logger
from nonebot.matcher import Matcher
from nonebot_plugin_apscheduler import scheduler

from src.models.schemas import ReminderRecord
from src.services.chat.policy import ChatAddress
from src.services.delivery.reminder import ReminderBook, ReminderIntentParser, generate_job_id
from src.services.delivery.reminder_delivery import ReminderDelivery
from src.services.delivery.reminder_schedule import ReminderSchedule
from src.services.delivery import dispatcher
from src.services.delivery.dispatcher import send_to_event
from src.services.persistence import StorageService

reminder_parser = ReminderIntentParser()
_storage = StorageService()
reminder_book = ReminderBook(storage=_storage)
_reminder_lock = asyncio.Lock()


async def _runtime():
    client = await asyncio.to_thread(lambda: _storage.redis)
    dispatcher.configure_outbound()
    return ReminderSchedule(client, scheduler, send_group_reminder,
                            lock=_reminder_lock, wait_seconds=dispatcher.outbound.required_wait)


async def send_group_reminder(job_id: str, version: str, valid_until_ms: int) -> None:
    try:
        runtime = await _runtime()
        snapshot = await asyncio.to_thread(runtime.source.load, job_id)
        if snapshot is None or snapshot.revision != version:
            return
        bot_id = snapshot.intent.get("bot_id")
        bot = get_bot(bot_id) if bot_id else get_bot()
        delivery = ReminderDelivery(runtime.source.redis,
                                    queued_lease_seconds=runtime.wait_seconds + 60)
        if not await delivery.deliver(bot, job_id, version, valid_until_ms=valid_until_ms):
            logger.warning("提醒未确认送达，保留持久化状态: {}", job_id)
    except Exception:
        logger.exception("提醒发送或持久化结果未确认，禁止自动重发")


def _parse_remind_time(value: object) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return None


@get_driver().on_startup
async def restore_persisted_reminders() -> None:
    try:
        runtime = await _runtime()
        restored = await runtime.restore()
        logger.info("未来提醒缓存恢复完成 count={}；过期项保留待核对", restored)
    except Exception:
        logger.exception("提醒恢复未完成，持久化记录保留；未回退内存发送")


async def _find_snapshot(runtime, address, event, keyword):
    current = await asyncio.to_thread(reminder_book.find, address.session_id, keyword,
                                      user_id=event.user_id)
    if current is None:
        return None
    snapshot = await asyncio.to_thread(runtime.source.load, current.job_id)
    if snapshot is None:
        return None
    item = snapshot.record
    if (item.session_id, item.user_id, item.group_id, item.content, item.remind_time) != (
            address.session_id, event.user_id, event.group_id, current.content, current.remind_time):
        return None
    return snapshot


async def handle_reminder(matcher: Matcher, event: MessageEvent,
                          address: ChatAddress, user_text: str) -> bool:
    data = await reminder_parser.parse(user_text, datetime.now())
    intent = str(data.get("intent", "NONE")).upper()
    if intent == "NONE":
        return False
    if not isinstance(event, GroupMessageEvent):
        await send_to_event(matcher, event, "提醒功能只能在群聊中使用哦~(￣▽￣)σ")
        return True
    if intent not in {"CREATE", "MODIFY", "DELETE"}:
        return False
    try:
        runtime = await _runtime()
        if intent == "CREATE":
            content = str(data.get("content") or "").strip()
            when = _parse_remind_time(data.get("remind_time"))
            if not content or when is None:
                await send_to_event(matcher, event, "茉子没听清时间和内容呢，请说得再清楚一点嘛~")
                return True
            if when.timestamp() <= datetime.now().timestamp():
                await send_to_event(matcher, event, "提醒时间已经过去了，请指定一个未来的时间。")
                return True
            item = ReminderRecord(reminder_id=generate_job_id(event.group_id, event.user_id, when),
                session_id=address.session_id, user_id=event.user_id, group_id=event.group_id,
                content=content, remind_time=when)
            change = await runtime.create(item, str(event.self_id))
        else:
            keyword = str(data.get("target_content") or "").strip()
            snapshot = await _find_snapshot(runtime, address, event, keyword) if keyword else None
            if snapshot is None:
                await send_to_event(matcher, event, "未找到匹配的当前提醒，请查看提醒列表后再操作。")
                return True
            item = snapshot.record
            if intent == "DELETE":
                change = await runtime.cancel(snapshot)
            else:
                when = _parse_remind_time(data.get("new_remind_time")) or item.remind_time
                content = str(data.get("new_content") or item.content).strip()
                if when.timestamp() <= datetime.now().timestamp():
                    await send_to_event(matcher, event, "提醒时间已经过去了，请指定一个未来的时间再修改。")
                    return True
                item = item.model_copy(update={"remind_time": when, "content": content})
                change = await runtime.replace(snapshot, item, str(event.self_id))
    except Exception:
        logger.exception("提醒变更的持久化结果未确认")
        await send_to_event(matcher, event,
            "提醒操作结果未确认，记录可能已改变；请查看提醒列表核对，勿重复操作。")
        return True

    if not change.mutation.ok:
        reply = "提醒未变更，记录可能已更新、重复或时间已过；请查看当前提醒后再操作。"
    elif intent == "DELETE":
        reply = f"关于“{item.content}”的后续提醒已取消。"
        if not change.cache_confirmed:
            reply += " 调度缓存清理未确认，旧任务发送前仍会被持久化版本检查拒绝。"
    elif not change.cache_confirmed:
        reply = "提醒记录已保存，但调度尚未确认；请核对状态，勿重复创建或修改。"
    else:
        reply = ("提醒已更新" if intent == "MODIFY" else "记下啦")
        reply += f"~ 茉子会在 {item.remind_time.strftime('%m月%d日 %H:%M')} 提醒你：{item.content}"
    if change.mutation.ok and intent != "CREATE" and change.mutation.delivery_state in {
            "sending", "unknown", "sent", "uninspected"}:
        reply += " 旧提醒可能已进入发送或已经送达，无法撤回；请核对群消息。"
    await send_to_event(matcher, event, reply)
    return True


def format_reminders(session_id: str, *, user_id: Optional[int] = None) -> str:
    reminders = reminder_book.list(session_id, user_id=user_id)
    if not reminders:
        return "你当前没有设置任何提醒哦~"
    lines = ["这是你设置的提醒列表："]
    lines.extend(f"{index}. [{item.remind_time.strftime('%m-%d %H:%M')}] {item.content}"
                 for index, item in enumerate(reminders, start=1))
    return "\n".join(lines)
