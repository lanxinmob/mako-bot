from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from src.services.chat_context import (
    LOCAL_TZ,
    SearchContextBuilder,
    build_time_context,
    normalize_search_queries,
    query_with_time_hint,
)
from src.services.search import SearchResult


def test_normalize_search_queries_deduplicates_and_caps() -> None:
    queries = normalize_search_queries(
        ["  Alpha  ", "alpha", "Beta", "Gamma", "Delta", "Echo"]
    )
    assert queries == ["Alpha", "Beta", "Gamma"]


def test_time_context_and_query_hint_use_explicit_clock() -> None:
    now = datetime(2026, 7, 10, 12, 0, tzinfo=LOCAL_TZ)
    context = build_time_context(now)
    assert "今天=2026-07-10" in context
    assert "昨天=2026-07-09" in context
    assert "明天=2026-07-11" in context
    assert "2026-07-09" in query_with_time_hint("昨天比赛结果", now)


@pytest.mark.asyncio
async def test_search_context_uses_planned_queries_and_deduplicates_links() -> None:
    async def search(query: str, num: int):
        return [
            SearchResult("结果 A", "https://example.com/a", "明确证据"),
            SearchResult("重复 A", "https://example.com/a", "重复证据"),
        ]

    builder = SearchContextBuilder(search=search)
    builder.plan_queries = AsyncMock(return_value=["赛事 2026 比分"])
    context = await builder.build("具体比分是多少", recent_history=[])

    assert "赛事 2026 比分" in context
    assert context.count("https://example.com/a") == 1
    assert "不要猜测" in context


@pytest.mark.asyncio
async def test_url_summary_fetch_failure_becomes_evidence_text() -> None:
    async def fetch(url: str, max_chars: int):
        raise RuntimeError("timeout")

    builder = SearchContextBuilder(fetch=fetch)
    context = await builder.build("总结 https://example.com/article")
    assert "链接内容读取失败" in context
    assert "timeout" in context
