from __future__ import annotations
from nonebot import get_bot
from nonebot.log import logger
from nonebot_plugin_apscheduler import scheduler
from src.services.autonomy.planning import decide
from src.services.autonomy.workflow import handle_decision
from .runtime import context

last_scan_at = 0.0


@scheduler.scheduled_job("interval", minutes=max(1, context.settings.autonomy_scan_minutes), id="mako_autonomy_scan")
async def autonomy_scan():
    global last_scan_at
    ctx = context
    if not ctx.policy.is_enabled():
        return
    if ctx.clock() - last_scan_at < max(60, ctx.settings.autonomy_scan_minutes * 60 - 5):
        return
    last_scan_at = ctx.clock()
    try:
        bot = get_bot()
        decision = await decide(ctx)
        await handle_decision(ctx, bot, decision)
    except Exception as exc:
        logger.warning(f"自主行动定时扫描失败: {exc}")
