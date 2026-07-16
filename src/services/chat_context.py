"""Context-enrichment phase for the chat request pipeline.

Image understanding and web evidence gathering are intentionally completed
before prompt construction.  External text is returned as labelled evidence so
the generation phase can consistently treat it as untrusted input.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, List, Optional

from nonebot.log import logger

from src.core.config import get_settings
from src.services.chat_policy import compact_text
from src.services.image import describe_image_url
from src.services.intent import decide_intents
from src.services.llm import get_deepseek_client, get_deepseek_model, has_deepseek
from src.services.reminder import extract_json_object
from src.services.search import SearchResult, fetch_page_text, web_search


LOCAL_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")
MAX_IMAGES_TO_DESCRIBE = 3
MAX_SEARCH_RESULTS = 5
MAX_SEARCH_CONTEXT_RESULTS = 3
MAX_SEARCH_QUERIES = 3
MAX_SEARCH_SNIPPET_CHARS = 240
MAX_URL_CONTEXT_CHARS = 3000


@dataclass(frozen=True)
class EnrichedChatInput:
    user_text: str
    llm_text: str
    image_context: str = ""
    search_context: str = ""


class ImageRateLimiter:
    def __init__(self, interval_seconds: Optional[int] = None) -> None:
        self.interval_seconds = (
            get_settings().image_rate_limit_seconds
            if interval_seconds is None
            else interval_seconds
        )
        self._last_seen: dict[int, float] = {}

    def allow(self, user_id: int, *, now: Optional[float] = None) -> bool:
        current = time.time() if now is None else now
        last = self._last_seen.get(user_id, 0.0)
        if current - last < self.interval_seconds:
            return False
        self._last_seen[user_id] = current
        return True


def build_time_context(now: Optional[datetime] = None) -> str:
    current = now or datetime.now(LOCAL_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=LOCAL_TZ)
    today = current.date()
    return (
        f"当前时间：{current.strftime('%Y-%m-%d %H:%M:%S %Z')}；"
        f"今天={today.isoformat()}；昨天={(today - timedelta(days=1)).isoformat()}；"
        f"明天={(today + timedelta(days=1)).isoformat()}。"
    )


def compact_recent_history(
    history: List[dict], max_turns: int = 6, max_chars: int = 900
) -> str:
    lines: List[str] = []
    for message in history[-max_turns:]:
        content = compact_text(message.get("content", ""), 180)
        if content:
            lines.append(f"{message.get('role', 'unknown')}: {content}")
    return compact_text("\n".join(lines), max_chars)


def normalize_search_queries(queries: object) -> List[str]:
    if not isinstance(queries, list):
        return []
    normalized: List[str] = []
    seen: set[str] = set()
    for value in queries:
        query = " ".join(str(value or "").split())[:180]
        key = query.lower()
        if len(query) < 2 or key in seen:
            continue
        seen.add(key)
        normalized.append(query)
        if len(normalized) >= MAX_SEARCH_QUERIES:
            break
    return normalized


def needs_strict_fact_check(text: str) -> bool:
    terms = (
        "最新", "新闻", "最近", "近期", "当前", "实时", "今天", "今日",
        "昨天", "昨日", "结果", "比分", "赛果", "战报", "战绩", "冠军",
        "决赛", "价格", "股价", "汇率", "票房", "现任", "发布", "更新",
    )
    return any(term in text for term in terms)


def query_with_time_hint(query: str, now: Optional[datetime] = None) -> str:
    current = now or datetime.now(LOCAL_TZ)
    today = current.date()
    additions: List[str] = []
    if any(token in query for token in ("昨天", "昨日")):
        additions.append(f"昨天 {today - timedelta(days=1)}")
    if any(token in query for token in ("今天", "今日")):
        additions.append(f"今天 {today}")
    if "明天" in query:
        additions.append(f"明天 {today + timedelta(days=1)}")
    if needs_strict_fact_check(query):
        additions.append(f"{today.year} 官方 来源 日期 结果")
    return " ".join((query, *additions))[:300] if additions else query


def query_with_image_hint(query: str, image_context: str) -> str:
    if not image_context or not any(
        token in query for token in ("图", "图片", "这张", "这个", "它", "上面", "里面")
    ):
        return query
    return " ".join(f"{query} 图片内容：{' '.join(image_context.split())}".split())[:300]


def truncate_search_text(text: str, max_chars: int = MAX_SEARCH_SNIPPET_CHARS) -> str:
    compact = " ".join((text or "").split())
    return compact if len(compact) <= max_chars else compact[:max_chars].rstrip() + "..."


class SearchContextBuilder:
    def __init__(
        self,
        *,
        search: Callable[..., Awaitable[List[SearchResult]]] = web_search,
        fetch: Callable[..., Awaitable[str]] = fetch_page_text,
    ) -> None:
        self.search = search
        self.fetch = fetch

    async def plan_queries(
        self,
        user_text: str,
        *,
        image_context: str = "",
        recent_history: Optional[List[dict]] = None,
    ) -> List[str]:
        if not has_deepseek():
            return []
        prompt = f"""
你是联网检索规划器。把用户消息改写成一到三个可独立检索的事实问题，不要回答用户。
要求：补全追问中的省略指代；加入必要的实体、日期、版本或届次；除非用户点名，否则不指定网站；只返回 JSON。

{build_time_context()}
最近聊天：{compact_recent_history(recent_history or []) or '无'}
图片描述：{image_context or '无'}
用户消息：{user_text}
返回格式：{{"queries":["查询1","查询2"],"reason":"一句话策略"}}
"""
        try:
            response = await asyncio.wait_for(
                get_deepseek_client().chat.completions.create(
                    model=get_deepseek_model(),
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.0,
                    max_tokens=500,
                ),
                timeout=12.0,
            )
            raw = response.choices[0].message.content or ""
            data = extract_json_object(raw)
            queries = normalize_search_queries(data.get("queries") if data else None)
            if queries:
                logger.info("联网搜索规划完成 queries={}", " || ".join(queries))
            else:
                logger.warning("联网搜索规划无有效查询 raw={}", compact_text(raw, 240))
            return queries
        except Exception as exc:
            logger.warning(f"联网搜索规划失败: {exc}")
            return []

    async def build(
        self,
        user_text: str,
        *,
        image_context: str = "",
        recent_history: Optional[List[dict]] = None,
    ) -> str:
        decisions = decide_intents(
            user_text, has_image=bool(image_context), has_audio=False, face_ids=[]
        )
        relevant = [
            item
            for item in decisions
            if item.name in {"search.web", "search.summarize_url"}
        ][:2]
        blocks: List[str] = []
        for decision in relevant:
            if decision.name == "search.summarize_url":
                url = decision.args.get("url", "")
                if not url:
                    continue
                try:
                    page = await self.fetch(url, max_chars=MAX_URL_CONTEXT_CHARS)
                    blocks.append(
                        f"链接内容摘录：{url}\n{page}"
                        if page
                        else f"链接内容为空或无法读取：{url}"
                    )
                except Exception as exc:
                    logger.warning(f"链接内容读取失败: {exc}")
                    blocks.append(f"链接内容读取失败：{url}，原因：{exc}")
                continue

            queries = await self.plan_queries(
                user_text,
                image_context=image_context,
                recent_history=recent_history,
            )
            if not queries:
                blocks.append(
                    f"{build_time_context()}\n联网搜索规划失败：未能生成可靠检索问题，因此没有执行搜索。"
                )
                continue
            lines = [
                "[联网事实核验]",
                f"时间上下文：{build_time_context()}",
                "搜索查询：",
                *[f"- {query}" for query in queries],
                "候选证据：",
            ]
            seen_links: set[str] = set()
            total = 0
            for index, planned in enumerate(queries, start=1):
                query = query_with_time_hint(query_with_image_hint(planned, image_context))
                try:
                    results = await self.search(query, num=MAX_SEARCH_RESULTS)
                except Exception as exc:
                    logger.warning(f"联网搜索失败: {exc}")
                    lines.append(f"查询{index}失败：{exc}")
                    continue
                used: List[SearchResult] = []
                for result in results:
                    key = (result.link or "").strip().lower()
                    if key and key in seen_links:
                        continue
                    if key:
                        seen_links.add(key)
                    used.append(result)
                    if len(used) >= MAX_SEARCH_CONTEXT_RESULTS:
                        break
                total += len(used)
                lines.append(f"查询{index}：{query}")
                for result_index, result in enumerate(used, start=1):
                    lines.append(
                        f"{index}.{result_index}. {truncate_search_text(result.title, 120)}\n"
                        f"   链接：{result.link}\n"
                        f"   摘要：{truncate_search_text(result.snippet)}"
                    )
            if total == 0:
                lines.append("所有规划查询都没有得到可用候选证据。")
            if needs_strict_fact_check(user_text):
                lines.append(
                    "回答约束：若证据没有直接支持日期、对象和结论，必须明确说没有查到可靠证据；不要猜测。"
                )
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)


class ChatContextBuilder:
    def __init__(
        self,
        *,
        search_builder: Optional[SearchContextBuilder] = None,
        image_limiter: Optional[ImageRateLimiter] = None,
        describe: Callable[[str], Awaitable[str]] = describe_image_url,
    ) -> None:
        self.search_builder = search_builder or SearchContextBuilder()
        self.image_limiter = image_limiter or ImageRateLimiter()
        self.describe = describe

    async def build(
        self,
        *,
        user_id: int,
        user_text: str,
        image_urls: List[str],
        history: List[dict],
    ) -> EnrichedChatInput:
        image_context = ""
        if image_urls and self.image_limiter.allow(user_id):
            image_context = await self._describe_images(image_urls)
        elif image_urls:
            logger.info(
                "图片处理被速率限制拦截 user_id={} image_count={}",
                user_id,
                len(image_urls),
            )

        llm_text = user_text
        if image_urls:
            image_evidence = image_context or "图片识别未返回可用结果。"
            llm_text = f"{user_text or '用户发送了图片。'}\n\n[图片识别结果]\n{image_evidence}"
        search_context = await self.search_builder.build(
            user_text,
            image_context=image_context,
            recent_history=history,
        )
        if search_context:
            llm_text = f"{llm_text}\n\n[联网搜索结果]\n{search_context}"
        return EnrichedChatInput(user_text, llm_text, image_context, search_context)

    async def _describe_images(self, image_urls: List[str]) -> str:
        async def describe_one(index: int, url: str) -> str:
            try:
                description = await self.describe(url)
                return f"第{index}张图片：{description or '图片识别没有返回可用描述。'}"
            except Exception as exc:
                logger.warning(f"图片识别失败({index}): {exc}")
                return f"第{index}张图片识别失败：{exc}"

        urls = image_urls[:MAX_IMAGES_TO_DESCRIBE]
        lines = await asyncio.gather(
            *(describe_one(index, url) for index, url in enumerate(urls, start=1))
        )
        remaining = len(image_urls) - len(urls)
        if remaining:
            lines.append(f"还有{remaining}张图片未识别。")
        return "\n".join(lines)
