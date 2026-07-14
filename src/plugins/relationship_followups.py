"""Scheduled delivery of due relationship promises."""

from __future__ import annotations

import asyncio

from nonebot import get_bot
from nonebot.adapters.onebot.v11 import Message
from nonebot.log import logger
from nonebot_plugin_apscheduler import scheduler

from src.core.config import get_settings
from src.services.outbound_dedup import OutboundDedupService
from src.services.relationship import RelationshipService
from src.services.storage import StorageService


settings = get_settings()
storage = StorageService()
relationship = RelationshipService(storage=storage)
dedup = OutboundDedupService(storage)


@scheduler.scheduled_job(
    "interval",
    minutes=max(1, settings.proactive_scan_minutes),
    id="mako_relationship_followups",
)
async def deliver_due_followups() -> None:
    if not settings.proactive_enabled:
        return
    due = await asyncio.to_thread(relationship.get_due_followups, 20)
    if not due:
        return
    bot = get_bot()
    for memory in due:
        message = f"之前说过要跟进这件事：{memory.content}\n现在进展怎么样啦？"
        decision = await asyncio.to_thread(
            dedup.check,
            target_type="private",
            target_id=memory.user_id,
            intent="reminder",
            content=message,
        )
        if not decision.allowed:
            continue
        try:
            await bot.send_private_msg(user_id=memory.user_id, message=Message(message))
            await asyncio.to_thread(
                dedup.record,
                target_type="private",
                target_id=memory.user_id,
                intent="reminder",
                content=message,
                source="relationship.followup",
            )
            await asyncio.to_thread(
                relationship.mark_done,
                memory.user_id,
                memory.memory_id,
            )
        except Exception:
            logger.exception(
                "关系跟进发送失败 user_id={} memory_id={}",
                memory.user_id,
                memory.memory_id,
            )
