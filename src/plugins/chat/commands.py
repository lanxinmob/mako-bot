from __future__ import annotations
import asyncio
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Message, MessageEvent, PrivateMessageEvent
from nonebot.params import CommandArg
from .runtime import relationship
from .ingress import _address
from .reminders import format_reminders

list_reminders_handler = on_command("我的提醒", aliases={"查看提醒"})
relationship_list_handler = on_command(
    "关系记忆",
    aliases={"我的记忆", "茉子记得什么"},
    priority=8,
    block=True,
)
relationship_correct_handler = on_command("纠正记忆", priority=8, block=True)
relationship_delete_handler = on_command("删除记忆", priority=8, block=True)


@list_reminders_handler.handle()
async def handle_list_reminders(event: MessageEvent) -> None:
    text = await asyncio.to_thread(
        format_reminders,
        _address(event).session_id,
        user_id=event.user_id,
    )
    await list_reminders_handler.finish(text)


def _private_memory_command(event: MessageEvent) -> bool:
    return isinstance(event, PrivateMessageEvent)


@relationship_list_handler.handle()
async def handle_relationship_list(event: MessageEvent) -> None:
    if not _private_memory_command(event):
        await relationship_list_handler.finish("关系记忆只在私聊里展示，免得把你的事说给群里听。")
    await relationship_list_handler.finish(relationship.format_memories(event.user_id))


@relationship_correct_handler.handle()
async def handle_relationship_correct(
    event: MessageEvent,
    args: Message = CommandArg(),
) -> None:
    if not _private_memory_command(event):
        await relationship_correct_handler.finish("请私聊茉子纠正关系记忆。")
    raw = args.extract_plain_text().strip()
    memory_id, separator, content = raw.partition(" ")
    if not separator or not memory_id or not content.strip():
        await relationship_correct_handler.finish("格式：纠正记忆 <记忆ID> <新的内容>")
    nickname = event.sender.card or event.sender.nickname or str(event.user_id)
    updated = relationship.correct_memory(
        event.user_id,
        memory_id,
        content,
        nickname=nickname,
    )
    if not updated:
        await relationship_correct_handler.finish("没有找到属于你的这条记忆，请先用“关系记忆”查看 ID。")
    await relationship_correct_handler.finish(f"已经改好记忆 {memory_id}：{updated.content}")


@relationship_delete_handler.handle()
async def handle_relationship_delete(
    event: MessageEvent,
    args: Message = CommandArg(),
) -> None:
    if not _private_memory_command(event):
        await relationship_delete_handler.finish("请私聊茉子删除关系记忆。")
    memory_id = args.extract_plain_text().strip()
    if not memory_id or " " in memory_id:
        await relationship_delete_handler.finish("格式：删除记忆 <记忆ID>")
    nickname = event.sender.card or event.sender.nickname or str(event.user_id)
    if not relationship.delete_memory(event.user_id, memory_id, nickname=nickname):
        await relationship_delete_handler.finish("没有找到属于你的这条记忆。")
    await relationship_delete_handler.finish(f"已经删除记忆 {memory_id}。")
