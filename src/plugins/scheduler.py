from __future__ import annotations

import random

from nonebot import get_bot, on_command
from nonebot.adapters.onebot.v11 import Message
from nonebot.log import logger
from nonebot.matcher import Matcher
from nonebot_plugin_apscheduler import scheduler

from src.core.config import get_settings
from src.services.news import fetch_juejin, fetch_tianxin

settings = get_settings()


def _render_news_block(title: str, items: list[dict]) -> str:
    if not items:
        return f"\n{title}\n- 今天这个分类暂无数据"
    lines = [f"\n{title}"]
    for idx, item in enumerate(items, start=1):
        lines.append(f"{idx}. {item['title']}")
        lines.append(f"   {item['description']}")
        lines.append(f"   {item['url']}")
    return "\n".join(lines)


async def _build_daily_digest() -> str:
    tech_news = await fetch_juejin(limit=2)
    game_news = await fetch_tianxin(api_name="game", limit=2)
    anime_news = await fetch_tianxin(api_name="dongman", limit=2)
    social_news = await fetch_tianxin(api_name="social", limit=2)

    parts = [
        "今日资讯速递",
        _render_news_block("技术前沿", tech_news),
        _render_news_block("游戏动态", game_news),
        _render_news_block("动漫资讯", anime_news),
        _render_news_block("社会热点", social_news),
    ]
    return "\n".join(parts)


@scheduler.scheduled_job("cron", hour=7, minute=0)
async def good_morning_mako() -> None:
    if not settings.default_group_id:
        return
    messages = [
        "早上好，今天也要打起精神。",
        "起床了，茉子大人来点名。",
        "新的一天开始了，先喝口水再出发。",
        "太阳都出来了，别赖床。",
    ]
    try:
        bot = get_bot()
        await bot.send_group_msg(group_id=settings.default_group_id, message=random.choice(messages))
    except Exception as exc:
        logger.warning(f"send good morning failed: {exc}")


@scheduler.scheduled_job("cron", hour=7, minute=10)
async def send_daily_digest() -> None:
    if not settings.default_group_id:
        return
    try:
        bot = get_bot()
        message = await _build_daily_digest()
        await bot.send_group_msg(group_id=settings.default_group_id, message=Message(message))
    except Exception as exc:
        logger.warning(f"send daily digest failed: {exc}")


daily_news_matcher = on_command("精选文章", aliases={"news", "今日新闻", "日报"}, priority=5, block=True)


@daily_news_matcher.handle()
async def handle_daily_news(matcher: Matcher) -> None:
    await matcher.send("正在整理今天的资讯...")
    try:
        msg = await _build_daily_digest()
        await matcher.finish(msg)
    except Exception as exc:
        await matcher.finish(f"资讯获取失败: {exc}")
