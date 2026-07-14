"""NoneBot entrypoint for the ordered chat request pipeline.

Protocol helpers live beside this module; domain and integration work lives in
``src.services``.  This file intentionally reads like a request phase table:
observe -> access -> route -> enrich -> generate -> present -> commit.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
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
from src.services.chat_policy import (
    ChatAddress,
    remaining_reply_delay,
    select_reply_plan,
    should_record_message,
    should_reply,
)
from src.services.chat_rhythm import ChatRhythmService
from src.services.governance import GovernanceService
from src.services.intent import decide_intents
from src.services.llm import has_deepseek, has_openai
from src.services.relationship import RelationshipService
from src.services.storage import StorageService
from src.services.tool_executor import ToolExecutor
from src.utils.message import normalize_message


settings = get_settings()
storage = StorageService()
audit = ChatAudit(storage)
context_builder = ChatContextBuilder()
relationship = RelationshipService(storage=storage)
governance = GovernanceService(storage=storage)
chat_rhythm = ChatRhythmService(storage=storage)


@dataclass
class _PendingTextBatch:
    version: int
    texts: list[str]
    matcher: Matcher
    event: MessageEvent
    bot: Bot
    started_at: float


_session_locks: dict[str, asyncio.Lock] = {}
_pending_text_batches: dict[tuple[str, int], _PendingTextBatch] = {}
_pending_batch_guard: asyncio.Lock | None = None


def _session_lock(session_id: str) -> asyncio.Lock:
    return _session_locks.setdefault(session_id, asyncio.Lock())


def _batch_guard() -> asyncio.Lock:
    global _pending_batch_guard
    if _pending_batch_guard is None:
        _pending_batch_guard = asyncio.Lock()
    return _pending_batch_guard


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
    """Debounce same-sender text fragments, then serialize one chat session."""

    started_at = time.perf_counter()
    normalized = normalize_message(event.get_message())
    user_text = await message_text(event, bot)
    address = _address(event)
    can_batch = bool(
        settings.chat_reply_debounce_seconds > 0
        and user_text
        and len(user_text) <= 80
        and not normalized.image_urls
        and not normalized.audio_urls
        and not normalized.face_ids
    )

    if can_batch:
        key = (address.session_id, event.user_id)
        async with _batch_guard():
            previous = _pending_text_batches.get(key)
            version = (previous.version + 1) if previous else 1
            texts = [*previous.texts, user_text] if previous else [user_text]
            batch = _PendingTextBatch(
                version=version,
                texts=texts,
                matcher=matcher,
                event=event,
                bot=bot,
                started_at=previous.started_at if previous else started_at,
            )
            _pending_text_batches[key] = batch
        await asyncio.sleep(settings.chat_reply_debounce_seconds)
        async with _batch_guard():
            latest = _pending_text_batches.get(key)
            if latest is None or latest.version != version:
                return
            _pending_text_batches.pop(key, None)
        matcher, event, bot = latest.matcher, latest.event, latest.bot
        user_text = "\n".join(latest.texts)
        started_at = latest.started_at
        normalized = normalize_message(event.get_message())
        address = _address(event)

    async with _session_lock(address.session_id):
        await _handle_chat_locked(
            matcher,
            event,
            bot,
            normalized=normalized,
            user_text=user_text,
            request_started_at=started_at,
        )


async def _handle_chat_locked(
    matcher: Matcher,
    event: MessageEvent,
    bot: Bot,
    *,
    normalized,
    user_text: str,
    request_started_at: float,
) -> None:
    """Run the ordered chat phases for one incoming OneBot event."""

    tool_executor = ToolExecutor()

    # ingress / observe
    nickname = event.sender.card or event.sender.nickname or str(event.user_id)
    address = _address(event)
    access = governance.can_chat(event.user_id, address.group_id)
    if not access.allowed:
        logger.info(
            "聊天访问被治理策略拒绝 user_id={} group_id={} reason={}",
            event.user_id,
            address.group_id,
            access.reason,
        )
        if access.reason == "durable storage is unavailable":
            await matcher.send(Message("持久化存储暂时不可用，茉子先不处理消息，避免丢失上下文。"))
        return
    if settings.llm_required and not (has_deepseek() or has_openai()):
        logger.error("聊天请求被拒绝：生产模式要求配置可用的 LLM")
        await matcher.send(Message("语言模型尚未配置，茉子暂时不能可靠地处理消息。"))
        return
    directed = event.is_tome() or isinstance(event, PrivateMessageEvent)
    will_reply = should_reply(
        user_text,
        is_to_me=directed,
        random_chance=settings.reply_random_chance,
    )
    rhythm = None
    if will_reply:
        rhythm = chat_rhythm.admit(
            address.session_id,
            message_type=event.message_type,
            sender_id=event.user_id,
        )
        if not rhythm.allowed:
            logger.info(
                "聊天节奏控制保持静默 user_id={} group_id={} reason={}",
                event.user_id,
                address.group_id,
                rhythm.reason,
            )
            return
    if should_record_message(
        message_type=event.message_type,
        directed=directed,
        will_reply=will_reply,
        record_undirected_group_messages=settings.record_undirected_group_messages,
    ):
        await asyncio.to_thread(
            _record_incoming,
            event,
            nickname=nickname,
            content=user_text,
            image_count=len(normalized.image_urls),
        )
        audit.progress(
            "message_received",
            "收到允许持久化的聊天消息并写入全局记忆。",
            {
                "user_id": event.user_id,
                "group_id": address.group_id,
                "is_tome": directed,
                "message_preview": user_text[:120],
                "image_count": len(normalized.image_urls),
            },
        )

    # access / route
    if not will_reply:
        return
    if rhythm and rhythm.boundary:
        boundary_plan = select_reply_plan(
            user_text,
            message_type=event.message_type,
            directed=directed,
            fast_exchange=True,
        )
        delay = remaining_reply_delay(
            boundary_plan,
            time.perf_counter() - request_started_at,
        )
        if delay:
            await asyncio.sleep(delay)
        boundary_text = chat_rhythm.boundary_text()
        await send_reply(matcher, event, bot, boundary_text)
        chat_rhythm.mark_sent(
            address.session_id,
            sender_id=event.user_id,
            boundary=True,
        )
        audit.progress(
            "chat_rhythm_boundary",
            "快速往返达到阈值，茉子主动收束并进入冷却。",
            {
                "user_id": event.user_id,
                "group_id": address.group_id,
                "known_bot": rhythm.known_bot,
                "automation_score": rhythm.automation_score,
                "rapid_turns": rhythm.rapid_turns,
            },
        )
        return
    if await handle_reminder(matcher, event, address, user_text):
        return

    try:
        await asyncio.to_thread(
            relationship.absorb_user_message,
            event.user_id,
            nickname,
            user_text,
        )
    except Exception as exc:
        logger.warning(f"关系记忆吸收失败，继续普通聊天: {exc}")

    try:
        # enrich
        try:
            history = await asyncio.to_thread(storage.get_history, address.session_id)
        except Exception as exc:
            logger.warning(f"聊天历史读取失败，已使用空历史继续: {exc}")
            history = []
        decisions = decide_intents(
            user_text,
            has_image=bool(normalized.image_urls),
            has_audio=bool(normalized.audio_urls),
            face_ids=normalized.face_ids,
        )
        # Search and basic image description are already part of the context
        # builder. Other capabilities are executed through the governed tool
        # boundary and their factual output is supplied to the model.
        tool_decisions = [
            item
            for item in decisions
            if item.name not in {"search.web", "search.summarize_url", "image.describe"}
        ]
        tool_result = await tool_executor.run(
            tool_decisions,
            event.user_id,
            user_text,
            normalized.image_urls,
            normalized.audio_urls,
            normalized.face_ids,
            message_type=event.message_type,
            group_id=address.group_id,
            is_group_admin=getattr(event.sender, "role", "member") in {"admin", "owner"},
        )
        enriched = await context_builder.build(
            user_id=event.user_id,
            user_text=user_text,
            image_urls=normalized.image_urls,
            history=history,
        )
        llm_text = enriched.llm_text
        if tool_result.context_text():
            llm_text += f"\n\n[工具执行结果]\n{tool_result.context_text()}"
        reply_plan = select_reply_plan(
            user_text,
            message_type=event.message_type,
            directed=directed,
            has_image=bool(normalized.image_urls),
            has_audio=bool(normalized.audio_urls),
            has_tool_result=bool(tool_result.context_text()),
            fast_exchange=bool(rhythm and rhythm.force_short),
        )
        request = ChatRequest(
            session_id=address.session_id,
            user_id=event.user_id,
            nickname=nickname,
            user_text=user_text,
            llm_text=llm_text,
            history=history,
            message_type=event.message_type,
            group_id=address.group_id,
            directed=directed,
            reply_plan=reply_plan,
            social_state=rhythm.social_state if rhythm else reply_plan.social_state,
        )

        input_chars = len(enriched.llm_text) + sum(
            len(str(item.get("content", ""))) for item in history
        )
        estimated_cost = governance.estimate_llm_cost(input_chars, reply_plan.max_chars)
        budget = await asyncio.to_thread(
            governance.can_consume_cost,
            event.user_id,
            estimated_cost,
        )
        if not budget.allowed:
            logger.warning(
                "聊天预算拒绝 user_id={} reason={} estimated_cost={:.4f}",
                event.user_id,
                budget.reason,
                estimated_cost,
            )
            await matcher.send(Message("今天的模型预算已经用完啦，晚些时候再来找茉子吧。"))
            return

        # generate
        reply = await chat_engine.generate(request)
        actual_cost = governance.estimate_llm_cost(input_chars, len(reply.text))
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
                "reply_mode": reply_plan.mode,
                "reply_max_chars": reply_plan.max_chars,
                "social_state": request.social_state,
            },
        )

        # present / commit
        delay = remaining_reply_delay(
            reply_plan,
            time.perf_counter() - request_started_at,
        )
        if delay:
            await asyncio.sleep(delay)
        await send_reply(matcher, event, bot, reply.text)
        chat_rhythm.mark_sent(address.session_id, sender_id=event.user_id)
        for extra_message in tool_result.extra_messages:
            await asyncio.sleep(0.35)
            await matcher.send(extra_message)
        try:
            await asyncio.to_thread(chat_engine.commit, request, reply)
            await asyncio.to_thread(governance.consume_cost, event.user_id, actual_cost)
        except Exception as exc:
            logger.warning(f"回复已发送但状态提交失败: {exc}")
        audit.progress(
            "reply_sent",
            "聊天回复已发送并提交历史。",
            {
                "user_id": event.user_id,
                "group_id": address.group_id,
                "reply_preview": reply.text[:160],
                "reply_mode": reply_plan.mode,
                "delay_seconds": round(delay, 3),
            },
        )
        logger.success(f"已回复: {reply.text[:50]}...")
    except asyncio.TimeoutError:
        logger.warning("聊天请求处理超时")
        await matcher.send(Message("茉子大人的新心脏好像有点过热了，等会儿再问嘛~"))
    except Exception as exc:
        logger.exception(f"聊天请求处理失败: {exc}")
        await matcher.send(Message("哼哼，茉子大人今天有点累了，不想理你~ (´-ω-`)"))
    finally:
        tool_executor.cleanup_temp_files()


@list_reminders_handler.handle()
async def handle_list_reminders(event: MessageEvent) -> None:
    text = await asyncio.to_thread(
        format_reminders,
        _address(event).session_id,
        user_id=event.user_id,
    )
    await list_reminders_handler.finish(text)


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
