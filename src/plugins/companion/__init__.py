"""Opt-in private commands and a quiet, recoverable polling scheduler."""
from nonebot import get_driver, get_bots, on_message, require
from nonebot.adapters.onebot.v11 import Bot, MessageEvent
from nonebot.matcher import Matcher
from nonebot.rule import Rule
from nonebot.log import logger

require('nonebot_plugin_apscheduler')
from nonebot_plugin_apscheduler import scheduler
from src.core.bootstrap import select_application_plugins
from src.core.config import get_settings
from src.services.persistence import StorageService
from src.services.governance.service import GovernanceService
from src.services.companion.commands import invoked
from src.services.companion.workflow import CompanionService
from src.services.companion.scanning import CompanionScanner
from .handler import handle

storage = StorageService()
governance = GovernanceService(storage)
service = CompanionService(storage)


def enabled():
    settings = get_settings()
    return 'companion' in select_application_plugins(settings.parse_name_list(settings.plugin_enable_list))


scanner = CompanionScanner(service,allowed=lambda user: enabled() and governance.can_chat(user).allowed,
                           bot_lookup=lambda bot_id: get_bots().get(bot_id))


async def requested(event: MessageEvent):
    return invoked(event.get_plaintext())


commands = on_message(rule=Rule(requested),priority=0,block=True)


@commands.handle()
async def command_entry(matcher: Matcher,event: MessageEvent,bot: Bot):
    await handle(matcher,event,bot,service,governance,enabled=enabled)


@get_driver().on_startup
async def recover_plans():
    await scan_plans()


@scheduler.scheduled_job('interval',seconds=30,id='mako_companion_scan',max_instances=1,coalesce=True)
async def scan_plans():
    try:
        await scanner.run()
    except Exception:
        logger.warning('考试陪伴扫描暂停：保存状态待确认，不回退内存或重发未知消息')
