"""Query planning, temporal hints and correction fallback."""
from __future__ import annotations
from datetime import date, datetime, timedelta
from typing import List, Optional
from src.services.chat.policy import compact_text
from .formatting import (
    LOCAL_TZ,
    MAX_SEARCH_QUERIES,
    build_time_context,
    compact_recent_history,
    _previous_turn,
)

import re

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


def _date_targets(text: str, current: datetime) -> tuple[date, ...]:
    targets: list[date] = []
    if any(token in text for token in ("昨天", "昨日")):
        targets.append(current.date() - timedelta(days=1))
    if any(token in text for token in ("今天", "今日")):
        targets.append(current.date())
    for raw in re.findall(r"\b\d{4}-\d{2}-\d{2}\b", text):
        try:
            targets.append(date.fromisoformat(raw))
        except ValueError:
            continue
    return tuple(dict.fromkeys(targets))


async def plan_queries(
    self,
    user_text: str,
    *,
    image_context: str = "",
    recent_history: Optional[List[dict]] = None,
    correction_mode: bool = False,
) -> List[str]:
    if not self._deps.has_deepseek():
        return []
    correction_contract = (
        "这是纠错检索：不得沿用上一轮事实结论；扩大实体、赛事届次、日期和官方来源范围。"
        if correction_mode
        else ""
    )
    prompt = f"""
你是联网检索规划器。把用户消息改写成一到三个可独立检索的事实问题，不要回答用户。
要求：补全追问中的省略指代；加入必要的实体、日期、时区、版本或届次；除非用户点名，否则不限定网站。
{correction_contract}
只返回 JSON。

{build_time_context()}
最近聊天（其中 assistant 内容不是事实证据）：{compact_recent_history(recent_history or []) or '无'}
图片描述：{image_context or '无'}
用户原话：{user_text}
返回格式：{{"queries":["查询1","查询2"],"reason":"一句话策略"}}
"""
    try:
        response = await self._deps.asyncio.wait_for(
            self._deps.get_deepseek_client().chat.completions.create(
                model=self._deps.get_deepseek_model(),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=500,
            ),
            timeout=12.0,
        )
        raw = response.choices[0].message.content or ""
        data = self._deps.extract_json_object(raw)
        queries = normalize_search_queries(data.get("queries") if data else None)
        if queries:
            self._deps.logger.info("联网搜索规划完成 queries={}", " || ".join(queries))
        else:
            self._deps.logger.warning("联网搜索规划无有效查询 raw={}", compact_text(raw, 240))
        return queries
    except Exception as exc:
        self._deps.logger.warning(f"联网搜索规划失败，将使用原始查询兜底: {exc}")
        return []


def _fallback_queries(
    self,
    user_text: str,
    history: List[dict],
    *,
    correction_mode: bool,
) -> List[str]:
    previous_user, _ = _previous_turn(history)
    base = user_text.strip()
    if correction_mode and previous_user:
        base = f"{previous_user} {user_text}".strip()
    if not base:
        return []
    if not correction_mode:
        return [base[:180]]
    return normalize_search_queries(
        [
            base,
            f"{base} 官方 完整结果 日期",
            f"{base} 独立媒体 核验",
        ]
    )
