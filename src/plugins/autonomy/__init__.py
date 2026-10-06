"""Owner message and scheduled autonomy plugin registration."""
from nonebot import on_message
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, PrivateMessageEvent
from nonebot.matcher import Matcher
from nonebot.log import logger
from src.services.autonomy.parsing import parse_decision
from .runtime import context
from . import owner


async def autonomy_rule(event: MessageEvent) -> bool:
    return await owner.autonomy_rule(context, event)


autonomy_handler = on_message(rule=autonomy_rule, priority=9, block=True)


@autonomy_handler.handle()
async def handle_autonomy_message(matcher: Matcher, event: MessageEvent, bot: Bot):
    if not isinstance(event, PrivateMessageEvent):
        return
    handled = await owner.process_owner_private(context, bot, matcher, event, event.get_plaintext().strip())
    if handled:
        await matcher.finish()


from . import scan
logger.success("茉子自主行动插件已成功加载!")
