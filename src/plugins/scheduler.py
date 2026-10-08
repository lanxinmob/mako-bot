"""Manual news queries and links."""

from __future__ import annotations

import asyncio
from datetime import date

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Message, MessageSegment, MessageEvent
from nonebot.log import logger
from nonebot.matcher import Matcher

from src.services.information.news import fetch_juejin
from src.services.information.news import fetch_tianxin
from src.services.information.news import yesterday
from src.services.persistence import StorageService
from src.services.delivery.dispatcher import send_to_event, send_notice


_storage = StorageService()
daily_news_matcher = on_command(
    "精选文章", aliases={"news", "今日新闻", "日报"}, priority=5, block=True
)
bilibili_matcher = on_command("bilibili", priority=5, block=True)


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


@daily_news_matcher.handle()
async def handle_daily_news(matcher: Matcher, event: MessageEvent) -> None:
    await send_notice(matcher, event, "茉子正在搜集最新资讯，请稍等片刻哦……",
                      notice_key="news.loading")
    try:
        digest_date, sections = await _fetch_digest_sections()
        if await send_to_event(matcher, event, _render_digest(digest_date, sections)):
            try:
                await asyncio.to_thread(_storage.record_sent_news, _digest_fingerprints(sections))
            except Exception:
                logger.warning("手动资讯已送达，文章指纹补记未确认；不重发消息")
    except Exception:
        logger.exception("手动资讯查询失败")
        await send_notice(matcher, event, "资讯服务暂时不可用，请稍后再试。",
                          notice_key="news.unavailable")


@bilibili_matcher.handle()
async def handle_bilibili(matcher: Matcher, event: MessageEvent) -> None:
    await send_to_event(matcher, event, "这是 Bilibili：\nhttps://www.bilibili.com/")
