"""Bounded background recovery; feature switches and frozen targets still apply."""
from __future__ import annotations

import asyncio
from datetime import date, datetime
import json

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
from src.services.delivery.periodic import PeriodicDelivery, period_deadline
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
        if spec.kind == "periodic":
            return ("scheduler" in selected and spec.target_type == "group"
                    and spec.target_id == str(settings.default_group_id)
                    and spec.business_id in {"scheduler.good_morning", "scheduler.daily_digest"}
                    and spec.revision == datetime.now(scheduler.timezone).date().isoformat())
        return False

    async def followup(bot, spec):
        return await FollowupDelivery(client, dedup).deliver(
            bot, int(spec.target_id), spec.business_id, recovery_spec=spec)

    async def reminder(bot, spec):
        return await ReminderDelivery(client).deliver(bot, spec.business_id, spec.revision,
            valid_until_ms=spec.valid_until_ms, recovery_spec=spec)

    async def periodic(bot, spec):
        period = date.fromisoformat(spec.revision)
        if spec.valid_until_ms != period_deadline(period, scheduler.timezone):
            return False
        body = json.loads(spec.payload)
        return await PeriodicDelivery(client, _storage, dedup).deliver(bot, int(spec.target_id),
            body["text"], task=spec.business_id, period=period, timezone=scheduler.timezone,
            intent=body["intent"], fingerprints=body["fingerprints"], recovery_spec=spec)

    return DeliveryRecovery(client, {"followup": followup, "reminder": reminder, "periodic": periodic},
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
