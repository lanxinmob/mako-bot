"""NoneBot adapter for daily knowledge and profile consolidation."""

from __future__ import annotations

from nonebot import on_command
from nonebot.log import logger
from nonebot.matcher import Matcher
from nonebot.params import ArgPlainText, CommandArg
from nonebot.adapters.onebot.v11 import Message
from nonebot_plugin_apscheduler import scheduler

from src.services.knowledge_precipitation import KnowledgePrecipitationService
from src.services.storage import StorageService


service = KnowledgePrecipitationService()
storage = StorageService()
memory_handler = on_command("可塑性记忆", aliases={"memory"}, priority=10, block=True)


@scheduler.scheduled_job("cron", hour=22, minute=0, id="mako_daily_knowledge")
async def precipitate_knowledge() -> None:
    try:
        result = await service.run(hours=24)
        if result.skipped_reason:
            logger.info("知识沉淀已跳过 reason={}", result.skipped_reason)
            return
        logger.success(
            "知识沉淀完成 records={} points={} profiles={}",
            result.records,
            result.knowledge_points,
            result.profiles_updated,
        )
    except Exception:
        logger.exception("知识沉淀任务失败")


@memory_handler.handle()
async def handle_first_receive(matcher: Matcher, args: Message = CommandArg()) -> None:
    if args.extract_plain_text():
        matcher.set_arg("target_id", args)


@memory_handler.got("target_id", prompt="要查看茉子对谁的印象~？")
async def handle_get_memory(target_id: str = ArgPlainText()) -> None:
    raw = target_id.strip()
    try:
        user_id = int(raw)
    except ValueError:
        await memory_handler.finish("用户 ID 必须是数字哦。")
        return
    try:
        profile = storage.get_profile(user_id)
    except Exception:
        logger.exception("用户画像读取失败 user_id={}", user_id)
        await memory_handler.finish("画像存储暂时不可用，请稍后再试。")
        return
    if not profile:
        await memory_handler.finish(f"茉子暂时没有对用户 {user_id} 的记忆。")
        return
    nickname = profile.get("nickname") or str(user_id)
    profile_text = profile.get("profile_text") or "记忆数据中缺少画像文本。"
    await memory_handler.finish(f"对 {nickname}（{user_id}）的茉子印象：\n\n{profile_text}")
