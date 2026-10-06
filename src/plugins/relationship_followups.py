"""Scheduled delivery of due relationship promises."""

from __future__ import annotations

import asyncio

from nonebot import get_bot
from nonebot.log import logger
from nonebot_plugin_apscheduler import scheduler

from src.core.config import get_settings
from src.services.delivery.dedup import OutboundDedupService
from src.services.delivery.followups import FollowupDelivery
from src.services.memory.relationship import RelationshipService
from src.services.persistence import StorageService


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
    client = await asyncio.to_thread(lambda: storage.redis)
    if client is None:
        logger.warning("关系跟进暂停：持久化存储不可用")
        return
    due = await asyncio.to_thread(relationship.get_due_followups, 20)
    if not due:
        return
    bot = get_bot()
    delivery = FollowupDelivery(client, dedup)
    for memory in due:
        try:
            acknowledged = await delivery.deliver(bot, memory.user_id, memory.memory_id)
            if not acknowledged:
                logger.warning("关系跟进未确认送达，保留待办 user_id={} memory_id={}",
                               memory.user_id, memory.memory_id)
                continue
        except Exception:
            logger.exception(
                "关系跟进发送失败 user_id={} memory_id={}",
                memory.user_id,
                memory.memory_id,
            )
