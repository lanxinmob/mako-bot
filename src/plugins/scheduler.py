"""Scheduled greetings and news delivery."""

from __future__ import annotations

import asyncio
import random
from datetime import date, datetime

from nonebot import get_bot, on_command
from nonebot.adapters.onebot.v11 import Message, MessageSegment
from nonebot.log import logger
from nonebot.matcher import Matcher
from nonebot_plugin_apscheduler import scheduler

from src.core.config import get_settings
from src.models.schemas import ChatRecord
from src.services.news import fetch_juejin, fetch_tianxin, yesterday
from src.services.outbound_dedup import OutboundDedupService
from src.services.storage import StorageService


_storage = StorageService()
_outbound_dedup = OutboundDedupService(_storage)
daily_news_matcher = on_command(
    "精选文章", aliases={"news", "今日新闻", "日报"}, priority=5, block=True
)
bilibili_matcher = on_command("bilibili", priority=5, block=True)


def _plain_text(message: object) -> str:
    return message.extract_plain_text() if isinstance(message, Message) else str(message)


async def _send_scheduled_group_message(
    bot,
    group_id: int | None,
    message: Message | str,
    *,
    intent: str,
    source: str,
) -> bool:
    if not group_id:
        logger.warning("定时消息未发送：DEFAULT_GROUP_ID 未配置 source={}", source)
        return False
    content = _plain_text(message)
    decision = await asyncio.to_thread(
        _outbound_dedup.check,
        target_type="group",
        target_id=group_id,
        intent=intent,
        content=content,
    )
    if not decision.allowed:
        logger.info(
            "跳过相似定时消息 group={} intent={} similarity={:.3f}",
            group_id,
            intent,
            decision.similarity,
        )
        return False
    await bot.send_group_msg(group_id=group_id, message=message)
    await asyncio.to_thread(
        _outbound_dedup.record,
        target_type="group",
        target_id=group_id,
        intent=intent,
        content=content,
        source=source,
    )
    await asyncio.to_thread(
        _storage.append_global_record,
        ChatRecord(role="assistant", content=content, group_id=group_id, time=datetime.now()),
    )
    return True


async def _fetch_digest_sections(
    *, target_date: date | None = None
) -> tuple[date, list[tuple[str, list[dict]]]]:
    digest_date = target_date or yesterday()
    sent_news = await asyncio.to_thread(_storage.list_sent_news)
    calls = [
        fetch_juejin(limit=2, target_date=digest_date, excluded=sent_news),
        fetch_tianxin(api_name="game", limit=2, target_date=digest_date, excluded=sent_news),
        fetch_tianxin(api_name="dongman", limit=2, target_date=digest_date, excluded=sent_news),
        fetch_tianxin(api_name="social", limit=2, target_date=digest_date, excluded=sent_news),
    ]
    results = await asyncio.gather(*calls, return_exceptions=True)
    titles = [
        "🚀 科技前沿",
        "🎮 游戏情报",
        "🌸 动漫资讯",
        "📰 社会新闻",
    ]
    sections: list[tuple[str, list[dict]]] = []
    seen_news = set(sent_news)
    for title, result in zip(titles, results):
        if isinstance(result, Exception):
            logger.warning("资讯抓取失败 section={} error={}", title, result)
            sections.append((title, []))
        else:
            unique_news: list[dict] = []
            for item in result:
                fingerprint = str(item.get("fingerprint", ""))
                if not fingerprint or fingerprint in seen_news:
                    continue
                seen_news.add(fingerprint)
                unique_news.append(item)
            sections.append((title, unique_news))
    return digest_date, sections


def _render_digest(digest_date: date, sections: list[tuple[str, list[dict]]]) -> Message:
    message = Message(f"{digest_date:%Y年%m月%d日}资讯快递到啦！\n")
    for title, news in sections:
        message.append(MessageSegment.text(f"\n{title}\n"))
        if not news:
            message.append(MessageSegment.text("暂无可用内容。\n"))
            continue
        for index, item in enumerate(news, start=1):
            message.append(
                MessageSegment.text(
                    f"{index}. {item.get('title', 'N/A')}\n"
                    f"   {item.get('description', '...')}\n"
                    f"   {item.get('url', '#')}\n"
                )
            )
    message.append(MessageSegment.text("\n今天的分享就到这里啦。"))
    return message


def _digest_fingerprints(sections: list[tuple[str, list[dict]]]) -> list[str]:
    return [
        str(item.get("fingerprint", ""))
        for _, news in sections
        for item in news
        if item.get("fingerprint")
    ]


@scheduler.scheduled_job("cron", hour=7, minute=0, id="mako_good_morning")
async def good_morning_mako() -> None:
    choices = [
        "早上好哦，各位！今天也是元气满满的一天~",
        "早上好！新的一天也要好好照顾自己哦。",
        "起床啦，别赖床，茉子等你来捣乱~",
        "太阳都晒屁股了，快起来开始今天的计划吧。",
    ]
    try:
        await _send_scheduled_group_message(
            get_bot(),
            get_settings().default_group_id,
            random.choice(choices),
            intent="greeting",
            source="scheduler.good_morning",
        )
    except Exception:
        logger.exception("早安消息发送失败")


@scheduler.scheduled_job("cron", hour=7, minute=10, id="mako_daily_digest")
async def send_daily_digest() -> None:
    try:
        digest_date, sections = await _fetch_digest_sections()
        message = _render_digest(digest_date, sections)
        sent = await _send_scheduled_group_message(
            get_bot(),
            get_settings().default_group_id,
            message,
            intent="daily_digest",
            source="scheduler.daily_digest",
        )
        if sent:
            await asyncio.to_thread(_storage.record_sent_news, _digest_fingerprints(sections))
    except Exception:
        logger.exception("每日资讯发送失败")


@daily_news_matcher.handle()
async def handle_daily_news(matcher: Matcher) -> None:
    await matcher.send("茉子正在搜集最新资讯，请稍等片刻哦……")
    try:
        digest_date, sections = await _fetch_digest_sections()
        await matcher.send(_render_digest(digest_date, sections))
        await asyncio.to_thread(_storage.record_sent_news, _digest_fingerprints(sections))
    except Exception:
        logger.exception("手动资讯查询失败")
        await matcher.send("资讯服务暂时不可用，请稍后再试。")


@bilibili_matcher.handle()
async def handle_bilibili(matcher: Matcher) -> None:
    await matcher.send("这是 Bilibili：\nhttps://www.bilibili.com/")
