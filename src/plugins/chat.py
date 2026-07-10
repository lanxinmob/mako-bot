"""NoneBot entrypoint for the ordered chat request pipeline.

Protocol helpers live beside this module; domain and integration work lives in
``src.services``.  This file intentionally reads like a request phase table:
observe -> access -> route -> enrich -> generate -> present -> commit.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from nonebot import on_command, on_message
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent, PrivateMessageEvent
from nonebot.log import logger
from nonebot.matcher import Matcher
from nonebot.params import CommandArg

from src.core.config import get_settings
from src.models.schemas import ChatRecord
from src.plugins.chat_delivery import message_text, send_reply
from src.plugins.chat_reminders import format_reminders, handle_reminder
from src.services.chat_audit import ChatAudit
from src.services.chat_context import ChatContextBuilder
from src.services.chat_engine import ChatEngine, ChatRequest
from src.services.chat_policy import ChatAddress, should_reply
from src.services.relationship import RelationshipService
from src.services.storage import StorageService
from src.utils.message import normalize_message


settings = get_settings()
storage = StorageService()
audit = ChatAudit(storage)
context_builder = ChatContextBuilder()
relationship = RelationshipService(storage=storage)


def _search_long_term_memory(query: str) -> list[str]:
    """Lazy-load the embedding stack only when a reply actually needs it."""

    from src.plugins.vector_db import search_db

    # Fetch extra candidates because private note vectors belonging to other
    # users are filtered by ChatEngine before prompt construction.
    return search_db(query, top_k=12)


chat_engine = ChatEngine(storage=storage, knowledge_search=_search_long_term_memory)
chat_handler = on_message(priority=40, block=True)
list_reminders_handler = on_command("我的提醒", aliases={"查看提醒"})
relationship_list_handler = on_command(
    "关系记忆",
    aliases={"我的记忆", "茉子记得什么"},
    priority=8,
    block=True,
)
relationship_correct_handler = on_command("纠正记忆", priority=8, block=True)
relationship_delete_handler = on_command("删除记忆", priority=8, block=True)


def _address(event: MessageEvent) -> ChatAddress:
    return ChatAddress(
        message_type=event.message_type,
        user_id=event.user_id,
        group_id=getattr(event, "group_id", None),
    )


def _record_incoming(
    event: MessageEvent,
    *,
    nickname: str,
    content: str,
    image_count: int,
) -> None:
    try:
        storage.append_global_record(
            ChatRecord(
                role="user",
                nickname=nickname,
                user_id=event.user_id,
                content=content or (f"[图片消息 {image_count}张]" if image_count else ""),
                group_id=getattr(event, "group_id", None),
                time=datetime.now(),
            )
        )
    except Exception as exc:
        logger.warning(f"写入用户聊天记录失败，继续处理消息: {exc}")


@chat_handler.handle()
async def handle_chat(matcher: Matcher, event: MessageEvent, bot: Bot) -> None:
    """Run the ordered chat phases for one incoming OneBot event."""

    # ingress / observe
    normalized = normalize_message(event.get_message())
    user_text = await message_text(event, bot)
    nickname = event.sender.card or event.sender.nickname or str(event.user_id)
    address = _address(event)
    _record_incoming(
        event,
        nickname=nickname,
        content=user_text,
        image_count=len(normalized.image_urls),
    )
    audit.progress(
        "message_received",
        "收到聊天消息并写入全局记忆。",
        {
            "user_id": event.user_id,
            "group_id": address.group_id,
            "is_tome": event.is_tome(),
            "message_preview": user_text[:120],
            "image_count": len(normalized.image_urls),
        },
    )

    # access / route
    if not should_reply(
        user_text,
        is_to_me=event.is_tome(),
        random_chance=settings.reply_random_chance,
    ):
        return
    if await handle_reminder(matcher, event, address, user_text):
        return

    try:
        relationship.absorb_user_message(event.user_id, nickname, user_text)
    except Exception as exc:
        logger.warning(f"关系记忆吸收失败，继续普通聊天: {exc}")

    try:
        # enrich
        try:
            history = storage.get_history(address.session_id)
        except Exception as exc:
            logger.warning(f"聊天历史读取失败，已使用空历史继续: {exc}")
            history = []
        enriched = await context_builder.build(
            user_id=event.user_id,
            user_text=user_text,
            image_urls=normalized.image_urls,
            history=history,
        )
        request = ChatRequest(
            session_id=address.session_id,
            user_id=event.user_id,
            nickname=nickname,
            user_text=user_text,
            llm_text=enriched.llm_text,
            history=history,
            message_type=event.message_type,
            group_id=address.group_id,
            directed=event.is_tome(),
        )

        # generate
        reply = await chat_engine.generate(request)
        audit.thought(
            "chat_reply_generated",
            "模型生成普通聊天回复；仅保存输入输出摘要，不保存隐藏推理链。",
            {
                "user_id": event.user_id,
                "group_id": address.group_id,
                "model": reply.model,
                "input_preview": enriched.llm_text[:160],
                "image_context_preview": enriched.image_context[:240],
                "search_context_preview": enriched.search_context[:320],
                "history_turns": len(history),
                "reply_preview": reply.text[:160],
            },
        )

        # present / commit
        await send_reply(matcher, event, bot, reply.text)
        try:
            chat_engine.commit(request, reply)
        except Exception as exc:
            logger.warning(f"回复已发送但状态提交失败: {exc}")
        audit.progress(
            "reply_sent",
            "聊天回复已发送并提交历史。",
            {
                "user_id": event.user_id,
                "group_id": address.group_id,
                "reply_preview": reply.text[:160],
            },
        )
        logger.success(f"已回复: {reply.text[:50]}...")
    except asyncio.TimeoutError:
        logger.warning("聊天请求处理超时")
        await matcher.send(Message("茉子大人的新心脏好像有点过热了，等会儿再问嘛~"))
    except Exception as exc:
        logger.exception(f"聊天请求处理失败: {exc}")
        await matcher.send(Message("哼哼，茉子大人今天有点累了，不想理你~ (´-ω-`)"))


@list_reminders_handler.handle()
async def handle_list_reminders(event: MessageEvent) -> None:
    await list_reminders_handler.finish(format_reminders(_address(event).session_id))


def _private_memory_command(event: MessageEvent) -> bool:
    return isinstance(event, PrivateMessageEvent)


@relationship_list_handler.handle()
async def handle_relationship_list(event: MessageEvent) -> None:
    if not _private_memory_command(event):
        await relationship_list_handler.finish("关系记忆只在私聊里展示，免得把你的事说给群里听。")
    await relationship_list_handler.finish(relationship.format_memories(event.user_id))


@relationship_correct_handler.handle()
async def handle_relationship_correct(
    event: MessageEvent,
    args: Message = CommandArg(),
) -> None:
    if not _private_memory_command(event):
        await relationship_correct_handler.finish("请私聊茉子纠正关系记忆。")
    raw = args.extract_plain_text().strip()
    memory_id, separator, content = raw.partition(" ")
    if not separator or not memory_id or not content.strip():
        await relationship_correct_handler.finish("格式：纠正记忆 <记忆ID> <新的内容>")
    nickname = event.sender.card or event.sender.nickname or str(event.user_id)
    updated = relationship.correct_memory(
        event.user_id,
        memory_id,
        content,
        nickname=nickname,
    )
    if not updated:
        await relationship_correct_handler.finish("没有找到属于你的这条记忆，请先用“关系记忆”查看 ID。")
    await relationship_correct_handler.finish(f"已经改好记忆 {memory_id}：{updated.content}")


@relationship_delete_handler.handle()
async def handle_relationship_delete(
    event: MessageEvent,
    args: Message = CommandArg(),
) -> None:
    if not _private_memory_command(event):
        await relationship_delete_handler.finish("请私聊茉子删除关系记忆。")
    memory_id = args.extract_plain_text().strip()
    if not memory_id or " " in memory_id:
        await relationship_delete_handler.finish("格式：删除记忆 <记忆ID>")
    nickname = event.sender.card or event.sender.nickname or str(event.user_id)
    if not relationship.delete_memory(event.user_id, memory_id, nickname=nickname):
        await relationship_delete_handler.finish("没有找到属于你的这条记忆。")
    await relationship_delete_handler.finish(f"已经删除记忆 {memory_id}。")


logger.success("茉子聊天插件已成功加载!")
