"""NoneBot adapter for daily knowledge and profile consolidation."""

from __future__ import annotations

import asyncio
from nonebot import get_driver, on_message
from nonebot.log import logger
from nonebot.matcher import Matcher
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent, MessageSegment
from nonebot_plugin_apscheduler import scheduler

from src.services.memory.knowledge_precipitation import KnowledgePrecipitationService
from src.services.persistence import StorageService
from src.core.config import get_settings
from src.services.memory.profile_view import ProfileViewService, is_profile_owner, parse_profile_command
from src.services.delivery.dispatcher import send_to_private
from src.features.discoveries.service import RepeatGate


service = KnowledgePrecipitationService()
storage = StorageService()
profile_view = ProfileViewService(storage)
profile_gate = RepeatGate()


def profile_argument(event, bot):
    if str(event.user_id) == str(bot.self_id):
        return None
    for segment in getattr(event, "original_message", event.get_message()):
        if segment.type == "at" and str(segment.data.get("qq")) != str(bot.self_id):
            return None
        if segment.type not in {"text", "at", "reply"}:
            return None
    nicknames = {"茉子", "mako", *getattr(get_driver().config, "nickname", set())}
    return parse_profile_command(event.get_plaintext(), nicknames)


async def profile_invoked(event: MessageEvent, bot: Bot):
    return profile_argument(event, bot) is not None


memory_handler = on_message(rule=profile_invoked, priority=9, block=True)


@scheduler.scheduled_job("cron", hour=22, minute=0, id="mako_daily_knowledge")
async def precipitate_knowledge() -> None:
    try:
        result = await service.run(hours=24)
        if result.skipped_reason:
            logger.info("知识沉淀已跳过 reason={}", result.skipped_reason)
            return
        logger.success(
            "知识沉淀完成 records={} points={} profiles={}",
            result.records,
            result.knowledge_points,
            result.profiles_updated,
        )
    except Exception:
        logger.exception("知识沉淀任务失败")


@memory_handler.handle()
async def handle_profiles(matcher: Matcher, event: MessageEvent, bot: Bot) -> None:
    argument = profile_argument(event, bot)

    def allowed():
        return is_profile_owner(event.user_id, get_settings().autonomy_owner_id)

    if argument is None or not allowed():
        await matcher.finish()
        return
    if not profile_gate.admit((str(bot.self_id), event.user_id), argument):
        await matcher.finish()
        return
    try:
        text = await asyncio.to_thread(profile_view.render, argument, user_id=event.user_id,
                                       owner_id=get_settings().autonomy_owner_id)
    except PermissionError:
        await matcher.finish()
        return
    except Exception:
        logger.warning("Owner profile lookup unavailable")
        text = "笔记暂时翻不开，稍后再试。"
    # Always reply privately; the shared guard checks ownership again at send time.
    await send_to_private(bot, event.user_id, Message(MessageSegment.text(text)),
                          category="command", guard=allowed)
    await matcher.finish()
