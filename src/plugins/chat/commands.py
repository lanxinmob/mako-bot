from __future__ import annotations
import asyncio
from nonebot import on_command, on_message
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from .ingress import _address
from .reminders import format_reminders
from .ledger_commands import handle, natural_invoked
from src.services.memory.ledger.commands import Command, parse

list_reminders_handler = on_command('我的提醒', aliases={'查看提醒', 'reminders'})
relationship_list_handler = on_command('关系记忆', aliases={'我的记忆', '茉子记得什么', 'memories'}, priority=8, block=True)
relationship_correct_handler = on_command('纠正记忆', aliases={'correct-memory'}, priority=8, block=True)
relationship_delete_handler = on_command('删除记忆', aliases={'忘掉记忆', 'forget-memory'}, priority=8, block=True)
relationship_explain_handler = on_command('解释记忆', aliases={'explain-memory'}, priority=8, block=True)
relationship_relearn_handler = on_command('重新记住', aliases={'relearn-memory'}, priority=8, block=True)
relationship_natural_handler = on_message(rule=natural_invoked, priority=8, block=True)


@list_reminders_handler.handle()
async def handle_list_reminders(event: MessageEvent):
    text = await asyncio.to_thread(format_reminders, _address(event).session_id, user_id=event.user_id)
    await list_reminders_handler.finish(text)


@relationship_list_handler.handle()
async def handle_relationship_list(matcher: Matcher, event: MessageEvent, bot: Bot):
    await handle(matcher, event, bot, Command('list'))


@relationship_correct_handler.handle()
async def handle_relationship_correct(matcher: Matcher, event: MessageEvent, bot: Bot, args: Message = CommandArg()):
    await handle(matcher, event, bot, parse('纠正记忆 ' + args.extract_plain_text()))


@relationship_delete_handler.handle()
async def handle_relationship_delete(matcher: Matcher, event: MessageEvent, bot: Bot, args: Message = CommandArg()):
    await handle(matcher, event, bot, parse('忘掉记忆 ' + args.extract_plain_text()))


@relationship_explain_handler.handle()
async def handle_explain(matcher: Matcher, event: MessageEvent, bot: Bot, args: Message = CommandArg()):
    await handle(matcher, event, bot, parse('解释记忆 ' + args.extract_plain_text()))


@relationship_relearn_handler.handle()
async def handle_relearn(matcher: Matcher, event: MessageEvent, bot: Bot, args: Message = CommandArg()):
    await handle(matcher, event, bot, parse('重新记住 ' + args.extract_plain_text()))


@relationship_natural_handler.handle()
async def handle_natural(matcher: Matcher, event: MessageEvent, bot: Bot):
    await handle(matcher, event, bot, parse(event.get_message().extract_plain_text()))
