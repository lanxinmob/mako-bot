from __future__ import annotations
import asyncio
from datetime import datetime
from nonebot.log import logger
from src.models.schemas import ChatRecord
from src.services.chat.policy import should_reply
from src.services.chat.policy import should_record_message
from src.services.integrations.llm import has_deepseek
from src.services.integrations.llm import has_openai
from src.services.memory.image_archive import get_image_archive, MAX_MEMORY_IMAGES
from .models import ChatInput, ChatServices, ChatTransport, Admission

def record_incoming(
    services: ChatServices,
    incoming: ChatInput,
    *,
    nickname: str,
    content: str,
    image_count: int,
) -> bool:
    try:
        services.storage.append_global_record(
            ChatRecord(
                role="user",
                nickname=nickname,
                user_id=incoming.address.user_id,
                content=content or (f"[图片消息 {image_count}张]" if image_count else ""),
                group_id=incoming.address.group_id,
                time=datetime.now(),
                image_urls=list(incoming.normalized.image_urls[:MAX_MEMORY_IMAGES]),
            )
        )
        return True
    except Exception as exc:
        logger.warning(f"写入用户聊天记录失败，继续处理消息: {exc}")
        return False


async def admit(services: ChatServices, incoming: ChatInput, transport: ChatTransport):
    user_text = incoming.text
    normalized = incoming.normalized
    # ingress / observe
    nickname = incoming.nickname
    address = incoming.address
    access = services.governance.can_chat(incoming.address.user_id, address.group_id)
    if not access.allowed:
        logger.info(
            "聊天访问被治理策略拒绝 user_id={} group_id={} reason={}",
            incoming.address.user_id,
            address.group_id,
            access.reason,
        )
        if access.reason == "durable storage is unavailable":
            await transport.notice("持久化存储暂时不可用，茉子先不处理消息，避免丢失上下文。")
        return
    if services.settings.llm_required and not (has_deepseek() or has_openai()):
        logger.error("聊天请求被拒绝：生产模式要求配置可用的 LLM")
        await transport.notice("语言模型尚未配置，茉子暂时不能可靠地处理消息。")
        return
    directed = incoming.directed
    will_reply = True if incoming.is_current is not None else should_reply(
        user_text,
        is_to_me=directed,
        random_chance=services.settings.reply_random_chance,
    )
    rhythm = None
    if will_reply and incoming.work_kind != "tool":
        rhythm = services.chat_rhythm.admit(
            address.session_id,
            message_type=incoming.address.message_type,
            sender_id=incoming.address.user_id,
        )
        if not rhythm.allowed:
            logger.info(
                "聊天节奏控制保持静默 user_id={} group_id={} reason={}",
                incoming.address.user_id,
                address.group_id,
                rhythm.reason,
            )
            return
    if not incoming.group_memory_observed and should_record_message(
        message_type=incoming.address.message_type,
        directed=directed,
        will_reply=will_reply,
        record_undirected_group_messages=services.settings.record_undirected_group_messages,
    ):
        recorded = await asyncio.to_thread(
            record_incoming,
            services,
            incoming,
            nickname=nickname,
            content=user_text,
            image_count=len(normalized.image_urls),
        )
        if recorded and normalized.image_urls:
            get_image_archive().enqueue(normalized.image_urls)
        services.audit.progress(
            "message_received",
            "收到允许持久化的聊天消息并写入全局记忆。",
            {
                "user_id": incoming.address.user_id,
                "group_id": address.group_id,
                "is_tome": directed,
                "message_preview": user_text[:120],
                "image_count": len(normalized.image_urls),
            },
        )

    return Admission(will_reply, rhythm)
