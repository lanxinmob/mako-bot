"""OneBot-specific input and output translation for the chat plugin."""

from __future__ import annotations

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


def render_group_text(text: str, name_to_user: dict[str, int]) -> Message:
    """Convert display-name occurrences to @ segments, preferring long names."""

    names = sorted(name_to_user, key=len, reverse=True)
    segments: list[MessageSegment] = []
    position = 0
    while position < len(text):
        name = next((item for item in names if text.startswith(item, position)), None)
        if name:
            segments.append(MessageSegment.at(name_to_user[name]))
            position += len(name)
        else:
            segments.append(MessageSegment.text(text[position]))
            position += 1
    return Message(segments)


async def send_reply(
    matcher: Matcher,
    event: MessageEvent,
    bot: Bot,
    text: str,
) -> None:
    """Render member display names as @ segments, with a text fallback."""

    if not isinstance(event, GroupMessageEvent):
        await matcher.send(Message(text))
        return
    try:
        members = await bot.get_group_member_list(group_id=event.group_id)
        name_to_user = {
            member.get("card") or member.get("nickname"): member["user_id"]
            for member in members
            if member.get("card") or member.get("nickname")
        }
        await matcher.send(
            MessageSegment.reply(event.message_id) + render_group_text(text, name_to_user)
        )
    except Exception as exc:
        logger.warning(f"群成员提及渲染失败，回退为纯文本: {exc}")
        await matcher.send(MessageSegment.reply(event.message_id) + Message(text))
