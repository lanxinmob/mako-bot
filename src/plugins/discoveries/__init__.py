"""Explicit discovery commands, before generic chat and after passive observation."""
import asyncio
from threading import Lock

from nonebot import get_driver, on_message
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent, MessageSegment
from nonebot.log import logger
from nonebot.matcher import Matcher

from src.core.config import get_settings
from src.features.discoveries.models import DiscoveryReply
from src.features.discoveries.service import DiscoveriesService, RepeatGate, parse_command
from src.services.delivery.dispatcher import send_to_group, send_to_private
from src.services.governance.service import GovernanceService
from src.services.tools.policy import is_enabled


service = DiscoveriesService()
repeat_gate = RepeatGate()
_governance = None
_governance_lock = Lock()


def command_for(event, bot):
    if str(event.user_id) == str(bot.self_id):
        return None
    # OneBot removes reply/at segments before rules run; retain the original target.
    for segment in getattr(event, "original_message", event.get_message()):
        if segment.type == "at" and str(segment.data.get("qq")) != str(bot.self_id):
            return None
        if segment.type not in {"text", "at", "reply"}:
            return None
    nicknames = {"茉子", "mako", *getattr(get_driver().config, "nickname", set())}
    return parse_command(event.get_plaintext(), nicknames)


async def invoked(event: MessageEvent, bot: Bot) -> bool:
    return command_for(event, bot) is not None


discoveries_handler = on_message(rule=invoked, priority=10, block=True)


def permitted(tool_name: str, event: MessageEvent) -> bool:
    global _governance
    settings = get_settings()
    if not is_enabled(tool_name, set(settings.parse_name_list(settings.tool_enable_list)),
                      set(settings.parse_name_list(settings.tool_disable_list))):
        return False
    with _governance_lock:
        if _governance is None:
            _governance = GovernanceService()
    return _governance.tool_allowed(
        tool_name, user_id=event.user_id, message_type=event.message_type,
        group_id=getattr(event, "group_id", None),
        is_group_admin=getattr(event.sender, "role", "member") in {"admin", "owner"},
    ).allowed


@discoveries_handler.handle()
async def handle_discovery(matcher: Matcher, event: MessageEvent, bot: Bot):
    command = command_for(event, bot)
    if command is None:
        await matcher.finish()
        return
    group_id = getattr(event, "group_id", None)
    tool_name = "discoveries." + ("journal" if command.kind == "suggest" else command.kind)

    async def allowed():
        try:
            return await asyncio.to_thread(permitted, tool_name, event)
        except Exception as exc:
            logger.warning("Discovery permission unavailable: {}", type(exc).__name__)
            return False

    if not await allowed():
        await matcher.finish()
        return
    key = (str(bot.self_id), event.message_type, group_id or event.user_id, event.user_id)
    if not repeat_gate.admit(key, command):
        await matcher.finish()
        return
    try:
        result = await service.run(command, user_id=event.user_id)
    except Exception as exc:
        logger.warning("Discovery command unavailable: {}", type(exc).__name__)
        result = DiscoveryReply("这次资料暂时没整理好，稍后再试。")
    # Structured text prevents metadata being parsed as CQ commands.
    message = Message(MessageSegment.text(result.text))
    if result.image_url:
        message.append(MessageSegment.image(result.image_url))
    # These shared adapters recheck permission at the send slot and stay silent
    # on revocation; event-adapter failure notices would be an extra unguarded send.
    if group_id is not None:
        await send_to_group(bot, group_id, message, category="command", guard=allowed)
    else:
        await send_to_private(bot, event.user_id, message, category="command", guard=allowed)
    await matcher.finish()
