from __future__ import annotations

import random
from typing import Optional

from nonebot import on_message
from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    Message,
    MessageEvent,
    MessageSegment,
)
from nonebot.log import logger
from nonebot.matcher import Matcher

from src.core.config import get_settings
from src.services.affinity import AffinityService
from src.services.chat_engine import ChatEngine
from src.services.emoji import analyze_emoji
from src.services.intent import decide_intents
from src.services.tool_executor import ToolExecutor
from src.utils.message import normalize_message

chat_handler = on_message(priority=40, block=True)

settings = get_settings()
chat_engine = ChatEngine()
tool_executor = ToolExecutor()
affinity_service = AffinityService()


def _is_for_mako(event: MessageEvent, text: str) -> bool:
    if event.message_type != "group":
        return True
    if event.is_tome():
        return True
    lower = text.lower()
    if "茉子" in text or "mako" in lower:
        return True
    return random.random() <= settings.reply_random_chance


def _is_non_text_directed(segment_types: list[str]) -> bool:
    return "at" in segment_types or "reply" in segment_types


def _nickname(event: MessageEvent) -> str:
    sender = event.sender
    return (sender.card or sender.nickname or str(event.user_id)).strip()


def _safe_text(text: str) -> str:
    return text.strip() if text else ""


def _build_reply_message(
    event: MessageEvent,
    text_reply: str,
    extra_segments: Optional[list[MessageSegment]] = None,
) -> Message:
    extra_segments = extra_segments or []
    if isinstance(event, GroupMessageEvent):
        msg = MessageSegment.reply(event.message_id) + MessageSegment.text(text_reply)
    else:
        msg = MessageSegment.text(text_reply)
    result = Message(msg)
    for seg in extra_segments:
        result.append(seg)
    return result


@chat_handler.handle()
async def handle_chat(matcher: Matcher, event: MessageEvent) -> None:
    raw_message = event.get_message()
    normalized = normalize_message(raw_message)
    text = _safe_text(normalized.plain_text)
    if not text and not normalized.segment_types:
        return

    dispatch_text = text or normalized.segment_summary
    if not _is_for_mako(event, dispatch_text):
        if not _is_non_text_directed(normalized.segment_types):
            return

    user_id = event.user_id
    nickname = _nickname(event)
    group_id = event.group_id if isinstance(event, GroupMessageEvent) else None
    session_id = chat_engine.session_key(event.message_type, user_id, group_id)

    image_urls = normalized.image_urls
    audio_urls = normalized.audio_urls
    face_ids = normalized.face_ids
    user_text = normalized.build_user_text()
    if not user_text:
        user_text = "我发送了一条消息。"

    emoji_result = analyze_emoji(face_ids, user_text)
    if emoji_result.affinity_delta:
        affinity_service.adjust(user_id, emoji_result.affinity_delta)

    decisions = decide_intents(
        text=text,
        has_image=bool(image_urls),
        has_audio=bool(audio_urls),
        face_ids=face_ids,
    )
    tool_result = await tool_executor.run(
        decisions=decisions,
        user_id=user_id,
        text=user_text,
        image_urls=image_urls,
        audio_urls=audio_urls,
        face_ids=face_ids,
    )

    base_context = normalized.segment_summary
    tool_context = tool_result.context_text()
    if base_context:
        tool_context = f"[原始消息段]\n{base_context}\n\n{tool_context}".strip()
    if emoji_result.labels:
        labels = "、".join(emoji_result.labels)
        extra_context = f"表情情绪识别：{labels}，sentiment={emoji_result.sentiment}"
        tool_context = f"{tool_context}\n{extra_context}".strip()

    try:
        reply = await chat_engine.generate_reply(
            session_id=session_id,
            user_id=user_id,
            nickname=nickname,
            user_text=user_text,
            tool_context=tool_context or None,
        )
    except Exception as exc:
        logger.exception(f"Chat generation failed: {exc}")
        if tool_context:
            reply = f"茉子先把结果给你：\n{tool_context}"
        else:
            reply = "茉子大人脑袋有点打结了，稍后再试试。"

    await matcher.send(_build_reply_message(event, reply, tool_result.extra_messages))


logger.success("chat plugin loaded.")
