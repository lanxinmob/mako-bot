"""OneBot/APScheduler adapter for the reminder domain."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from nonebot import get_bot
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageEvent, MessageSegment
from nonebot.log import logger
from nonebot.matcher import Matcher
from nonebot_plugin_apscheduler import scheduler

from src.services.chat_policy import ChatAddress
from src.services.reminder import (
    Reminder,
    ReminderBook,
    ReminderIntentParser,
    generate_job_id,
)


reminder_parser = ReminderIntentParser()
reminder_book = ReminderBook()


async def send_group_reminder(
    group_id: int,
    session_id: str,
    job_id: str,
    message: str,
    at_all: bool = False,
) -> None:
    try:
        bot = get_bot()
        outgoing = Message([])
        if at_all:
            outgoing.append(MessageSegment.at("all"))
        outgoing.append(MessageSegment.text(f" {message}"))
        await bot.send_group_msg(group_id=group_id, message=outgoing)
        reminder_book.remove(session_id, job_id)
        logger.success(f"已发送并清理提醒: {job_id}")
    except Exception as exc:
        logger.error(f"发送提醒失败: {exc}")


def _parse_remind_time(value: object) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _schedule_reminder(
    *,
    event: GroupMessageEvent,
    session_id: str,
    content: str,
    remind_time: datetime,
    replace_existing: bool = False,
) -> Reminder:
    job_id = generate_job_id(event.group_id, event.user_id, remind_time)
    scheduler.add_job(
        send_group_reminder,
        "date",
        run_date=remind_time,
        args=[event.group_id, session_id, job_id, content, False],
        id=job_id,
        misfire_grace_time=60,
        replace_existing=replace_existing,
    )
    reminder = Reminder(job_id=job_id, content=content, remind_time=remind_time)
    reminder_book.add(session_id, reminder)
    return reminder


async def handle_reminder(
    matcher: Matcher,
    event: MessageEvent,
    address: ChatAddress,
    user_text: str,
) -> bool:
    intent_data = await reminder_parser.parse(user_text, datetime.now())
    intent = str(intent_data.get("intent", "NONE")).upper()
    if intent == "NONE":
        return False
    if not isinstance(event, GroupMessageEvent):
        await matcher.send("提醒功能只能在群聊中使用哦~(￣▽￣)σ")
        return True

    if intent == "CREATE":
        content = str(intent_data.get("content") or "").strip()
        remind_time = _parse_remind_time(intent_data.get("remind_time"))
        if not content or remind_time is None:
            await matcher.send("茉子没听清时间和内容呢，请说得再清楚一点嘛~")
            return True
        reminder = _schedule_reminder(
            event=event,
            session_id=address.session_id,
            content=content,
            remind_time=remind_time,
        )
        await matcher.send(
            f"记下啦~ 茉子会在 {reminder.remind_time.strftime('%m月%d日 %H:%M')} "
            f"提醒你：{reminder.content}~(｡•̀ᴗ-)✧"
        )
        return True

    keyword = str(intent_data.get("target_content") or "").strip()
    current = reminder_book.find(address.session_id, keyword) if keyword else None
    if current is None:
        await matcher.send("茉子没找到你说的那个提醒哦，要不先看看提醒列表？")
        return True

    if intent == "DELETE":
        try:
            scheduler.remove_job(current.job_id)
        except Exception as exc:
            logger.warning(f"移除提醒任务失败: {exc}")
        reminder_book.remove(address.session_id, current.job_id)
        await matcher.send(f"好哦，关于“{current.content}”的提醒已经取消啦~")
        return True

    if intent == "MODIFY":
        new_time = _parse_remind_time(intent_data.get("new_remind_time")) or current.remind_time
        new_content = str(intent_data.get("new_content") or current.content).strip()
        try:
            updated = _schedule_reminder(
                event=event,
                session_id=address.session_id,
                content=new_content,
                remind_time=new_time,
                replace_existing=True,
            )
            if updated.job_id != current.job_id:
                scheduler.remove_job(current.job_id)
            reminder_book.remove(address.session_id, current.job_id)
        except Exception as exc:
            logger.exception(f"更新提醒失败: {exc}")
            await matcher.send("更新提醒时出了点问题，旧提醒可能仍然有效，请查看提醒列表确认。")
            return True
        await matcher.send(
            f"提醒已更新~ 茉子会在 {updated.remind_time.strftime('%m月%d日 %H:%M')} "
            f"提醒你：{updated.content}~(｡•̀ᴗ-)✧"
        )
        return True

    logger.warning(f"忽略未知提醒意图: {intent}")
    return False


def format_reminders(session_id: str) -> str:
    reminders = reminder_book.list(session_id)
    if not reminders:
        return "你当前没有设置任何提醒哦~"
    lines = ["这是你设置的提醒列表："]
    lines.extend(
        f"{index}. [{item.remind_time.strftime('%m-%d %H:%M')}] {item.content}"
        for index, item in enumerate(reminders, start=1)
    )
    return "\n".join(lines)

