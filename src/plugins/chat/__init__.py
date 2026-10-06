"""QQ chat plugin registration; implementation is separated by responsibility."""
from nonebot import on_message
from nonebot.adapters.onebot.v11 import Bot, MessageEvent
from nonebot.matcher import Matcher
from nonebot.log import logger
from .runtime import workflow
from .ingress import receive, observe
from . import commands
from . import recovery

group_observer = on_message(priority=1, block=False)
chat_handler = on_message(priority=40, block=True)


@group_observer.handle()
async def observe_chat(event: MessageEvent, bot: Bot) -> None:
    observe(event, bot, workflow)


@chat_handler.handle()
async def handle_chat(matcher: Matcher, event: MessageEvent, bot: Bot) -> None:
    await receive(matcher, event, bot, workflow)


logger.success("茉子聊天插件已成功加载!")
