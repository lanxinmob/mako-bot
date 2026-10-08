"""Bounded background recovery; feature switches and frozen targets still apply."""
from __future__ import annotations

import asyncio

from nonebot import get_bots
from nonebot.log import logger
from nonebot_plugin_apscheduler import scheduler

from src.core.bootstrap import select_application_plugins
from src.core.config import get_settings
from src.services.delivery.dedup import OutboundDedupService
from src.services.delivery.effects.discovery import EffectScanner
from src.services.chat.generation.discovery import GenerationCostScanner
from src.services.chat.history_delivery.discovery import HistoryScanner
from src.services.delivery.followups import FollowupDelivery
from src.services.delivery.reminder_delivery import ReminderDelivery
from src.services.delivery.state.recovery import DeliveryRecovery
from src.services.persistence import StorageService
from .reminders import _runtime as reminder_runtime

_storage = StorageService()
_cursor = "0:0"
_effects_cursor = "0:0"
_generation_cursor = "0:0"
_history_cursor = "0:0"
_reminder_cursor = "0:0"
_reminder_intents = False


def _runner(client, settings):
    selected = select_application_plugins(settings.parse_name_list(settings.plugin_enable_list))
    dedup = OutboundDedupService(_storage)

    def allowed(spec):
        if spec.kind == "reminder":
            return spec.target_type == "group"
        if spec.kind == "followup":
            return ("relationship_followups" in selected and settings.proactive_enabled
                    and spec.target_type == "private")
        return False

    async def followup(bot, spec):
        return await FollowupDelivery(client, dedup).deliver(
            bot, int(spec.target_id), spec.business_id, recovery_spec=spec)

    async def reminder(bot, spec):
        return await ReminderDelivery(client).deliver(bot, spec.business_id, spec.revision,
            valid_until_ms=spec.valid_until_ms, recovery_spec=spec)

    return DeliveryRecovery(client, {"followup": followup, "reminder": reminder},
                            bot_lookup=lambda bot_id: get_bots().get(bot_id), allowed=allowed)


@scheduler.scheduled_job("interval", seconds=30, id="mako_delivery_recovery", max_instances=1, coalesce=True)
async def recover_background_deliveries():
    global _cursor, _effects_cursor, _generation_cursor, _history_cursor, _reminder_cursor, _reminder_intents
    try:
        reminders = await reminder_runtime()
        next_reminder, _ = await reminders.restore_page(_reminder_cursor, intents=_reminder_intents)
        _reminder_cursor = next_reminder or "0:0"
        if next_reminder is None:
            _reminder_intents = not _reminder_intents
    except Exception:
        logger.warning("提醒调度恢复暂停：保留该分页位置与记录，其他发送恢复继续检查")
    try:
        client = await asyncio.to_thread(lambda: _storage.redis)
        runner = _runner(client, get_settings())
        following, _ = await runner.run_page(_cursor, limit=3)
        _cursor = following or "0:0"
    except Exception:
        logger.warning("后台发送恢复暂停：状态读取未确认；保留分页位置与执行证据")
    try:
        client = await asyncio.to_thread(lambda: _storage.redis)
        page = await EffectScanner(client).run_page(_effects_cursor)
        _effects_cursor = page.next_cursor or "0:0"
    except Exception:
        logger.warning("送达补记恢复暂停：保留分页位置及任务，不触发重发")
    try:
        client = await asyncio.to_thread(lambda: _storage.redis)
        await GenerationCostScanner(client).run_due()
    except Exception:
        logger.warning("到期费用消费暂停：保留记录及索引，不重新调用模型")
    try:
        client = await asyncio.to_thread(lambda: _storage.redis)
        page = await GenerationCostScanner(client).repair_page(_generation_cursor)
        _generation_cursor = page.next_cursor or "0:0"
    except Exception:
        logger.warning("费用索引修复暂停：保留分页位置，不重新调用模型")
    try:
        client = await asyncio.to_thread(lambda: _storage.redis)
        page = await HistoryScanner(client).run_page(_history_cursor)
        _history_cursor = page.next_cursor or "0:0"
    except Exception:
        logger.warning("聊天历史恢复暂停：保留分页位置及计划，不重发消息或调用模型")
