from __future__ import annotations

import random

from nonebot import get_bot, on_command
from nonebot.adapters.onebot.v11 import Message
from nonebot.log import logger
from nonebot.matcher import Matcher
from nonebot_plugin_apscheduler import scheduler

from src.core.config import get_settings
from src.services.news import fetch_juejin, fetch_tianxin
from src.services.relationship import RelationshipService
from src.services.storage import StorageService

settings = get_settings()
relationship = RelationshipService()
storage = StorageService()


def _render_news_block(title: str, items: list[dict]) -> str:
    if not items:
        return f"\n{title}\n- 今天该分类暂无数据"
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


@scheduler.scheduled_job("cron", hour=7, minute=0, id="mako_good_morning", replace_existing=True)
async def good_morning_mako() -> None:
    if not settings.default_group_id:
        return
    messages = [
        "早上好，今天也要打起精神。",
        "起床啦，茉子大人来点名。",
        "新的一天开始了，先喝口水再出发。",
        "太阳都出来了，别赖床。",
    ]
    try:
        bot = get_bot()
        await bot.send_group_msg(group_id=settings.default_group_id, message=random.choice(messages))
    except Exception as exc:
        logger.warning(f"send good morning failed: {exc}")


@scheduler.scheduled_job("cron", hour=7, minute=10, id="mako_daily_digest", replace_existing=True)
async def send_daily_digest() -> None:
    if not settings.default_group_id:
        return
    try:
        bot = get_bot()
        message = await _build_daily_digest()
        await bot.send_group_msg(group_id=settings.default_group_id, message=Message(message))
    except Exception as exc:
        logger.warning(f"send daily digest failed: {exc}")


@scheduler.scheduled_job(
    "interval",
    minutes=max(5, settings.proactive_scan_minutes),
    id="mako_proactive_followup",
    replace_existing=True,
)
async def proactive_followup_tick() -> None:
    if not settings.proactive_enabled:
        return
    due = relationship.get_due_followups(limit=20)
    if not due:
        return
    try:
        bot = get_bot()
    except Exception:
        return

    for mem in due:
        try:
            await bot.send_private_msg(
                user_id=mem.user_id,
                message=f"茉子大人来跟进一下：你之前提到“{mem.content}”，现在进展怎么样？",
            )
            relationship.mark_done(mem.user_id, mem.memory_id)
        except Exception as exc:
            logger.warning(f"proactive followup failed user={mem.user_id}, err={exc}")


@scheduler.scheduled_job("cron", hour=22, minute=30, id="mako_daily_recap", replace_existing=True)
async def daily_recap_tick() -> None:
    if not settings.default_group_id:
        return
    records = storage.get_recent_global_records(hours=24)
    if not records:
        return
    user_messages = [r for r in records if r.role == "user"]
    bot_messages = [r for r in records if r.role == "assistant"]
    top_topics = []
    for rec in user_messages[-10:]:
        snippet = rec.content.strip().replace("\n", " ")[:20]
        if snippet:
            top_topics.append(snippet)
    summary = (
        f"今日复盘:\n"
        f"- 用户消息: {len(user_messages)}\n"
        f"- 茉子回复: {len(bot_messages)}\n"
        f"- 近期话题: {' / '.join(top_topics[:3]) if top_topics else '无'}\n"
        f"有需要我可以继续跟进其中一个话题。"
    )
    try:
        bot = get_bot()
        await bot.send_group_msg(group_id=settings.default_group_id, message=Message(summary))
    except Exception as exc:
        logger.warning(f"daily recap failed: {exc}")


daily_news_matcher = on_command("精选文章", aliases={"news", "今日新闻", "日报"}, priority=5, block=True)
followup_matcher = on_command("待跟进", aliases={"followups"}, priority=5, block=True)


@daily_news_matcher.handle()
async def handle_daily_news(matcher: Matcher) -> None:
    await matcher.send("正在整理今天的资讯...")
    try:
        msg = await _build_daily_digest()
        await matcher.finish(msg)
    except Exception as exc:
        await matcher.finish(f"资讯获取失败: {exc}")


@followup_matcher.handle()
async def handle_followups(matcher: Matcher) -> None:
    due = relationship.get_due_followups(limit=5)
    if not due:
        await matcher.finish("当前没有到期的跟进事项。")
    lines = [f"- user={item.user_id} | {item.content}" for item in due]
    await matcher.finish("到期跟进:\n" + "\n".join(lines))
