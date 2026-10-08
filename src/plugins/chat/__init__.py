"""QQ chat plugin registration; implementation is separated by responsibility."""
from nonebot import get_driver, on_message
from nonebot.adapters.onebot.v11 import Bot, MessageEvent
from nonebot.matcher import Matcher
from nonebot.log import logger
from .runtime import workflow
from .ingress import receive, observe
from . import commands
from . import recovery
from src.services.memory.image_archive import get_image_archive

group_observer = on_message(priority=1, block=False)
chat_handler = on_message(priority=40, block=True)


@group_observer.handle()
async def observe_chat(event: MessageEvent, bot: Bot) -> None:
    await observe(event, bot, workflow)


@chat_handler.handle()
async def handle_chat(matcher: Matcher, event: MessageEvent, bot: Bot) -> None:
    await receive(matcher, event, bot, workflow)


@get_driver().on_shutdown
async def stop_memory_image_downloads():
    await get_image_archive().close()


logger.success("茉子聊天插件已成功加载!")
