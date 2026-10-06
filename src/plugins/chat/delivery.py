"""OneBot-specific input and output translation for the chat plugin."""

from __future__ import annotations
import inspect

from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupMessageEvent,
    Message,
    MessageEvent,
    MessageSegment,
)
from nonebot.log import logger
from nonebot.matcher import Matcher

from src.utils.message import normalize_message
from src.services.delivery.dispatcher import dispatch, Guard, Category, acknowledged_result


async def message_text(event: MessageEvent, bot: Bot) -> str:
    """Resolve group @ segments to display names and retain ordinary text."""

    raw = event.get_message()
    normalized = normalize_message(raw)
    if not isinstance(event, GroupMessageEvent):
        return normalized.plain_text

    parts: list[str] = []
    for segment in raw:
        if segment.type == "text":
            parts.append(str(segment.data.get("text", "")))
            continue
        if segment.type != "at":
            continue
        try:
            user_id = int(segment.data["qq"])
            member = await bot.get_group_member_info(
                group_id=event.group_id,
                user_id=user_id,
            )
            nickname = member.get("card") or member.get("nickname")
            if nickname:
                parts.append(f"{nickname} ")
        except Exception as exc:
            logger.debug(f"群成员名称解析失败，已忽略: {exc}")
    return "".join(parts).strip()


from src.utils.rendering import render_group_text


async def send_reply(
    matcher: Matcher,
    event: MessageEvent,
    bot: Bot,
    text: str,
    *,
    guard: Guard | None = None,
    category: Category = "chat",
    on_sent=None,
    before_send=None,
    on_ack=None,
) -> bool:
    """Render member display names as @ segments, with a text fallback."""

    async def admitted():
        if before_send is None:
            return True
        if await before_send() is not True:
            return False
        if guard is not None:
            allowed = guard()
            if inspect.isawaitable(allowed):
                allowed = await allowed
            if not allowed:
                return False
        return True

    if not isinstance(event, GroupMessageEvent):
        async def send_private():
            if not await admitted():
                return False
            acknowledged = acknowledged_result(await matcher.send(Message(text)))
            if acknowledged and on_ack is not None:
                on_ack()
            return acknowledged
        return await dispatch("private", event.user_id,
                              send_private, category=category, guard=guard)
    try:
        members = await bot.get_group_member_list(group_id=event.group_id)
        name_to_user = {
            member.get("card") or member.get("nickname"): member["user_id"]
            for member in members
            if member.get("card") or member.get("nickname")
        }
        payload = MessageSegment.reply(event.message_id) + render_group_text(text, name_to_user)
    except Exception as exc:
        logger.warning(f"群成员提及渲染失败，回退为纯文本: {exc}")
        payload = MessageSegment.reply(event.message_id) + Message(text)
    async def send():
        if not await admitted():
            return False
        result = await matcher.send(payload)
        acknowledged = acknowledged_result(result)
        if acknowledged and on_ack is not None:
            on_ack()
        if acknowledged and on_sent is not None:
            try:
                on_sent(result, text)
            except Exception as exc:
                logger.warning("回复已发送，参与状态更新失败: {}", exc)
        return acknowledged
    return await dispatch("group", event.group_id, send,
                          category=category, guard=guard)
