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
            SearchResult("结果 B", "https://example.org/b", "交叉证据"),
        ]

    async def fetch(url: str, max_chars: int):
        return "2026 赛事最终比分，网页正文已读取"

    async def verify(user_text, sources, correction_mode, disputed_answer):
        return {
            "status": "supported",
            "claims": [{"text": "赛事比分已确认", "source_ids": ["S1", "S2"]}],
        }

    builder = SearchContextBuilder(search=search, fetch=fetch, verifier=verify)
    builder.plan_queries = AsyncMock(return_value=["赛事 2026 比分"])
    outcome = await builder.build("具体比分是多少", recent_history=[])
    context = outcome.context_text()

    assert outcome.success is True
    assert "赛事 2026 比分" in context
    assert [source.url for source in outcome.sources].count("https://example.com/a") == 1
    assert "网页正文已打开并读取" in context


@pytest.mark.asyncio
async def test_url_summary_fetch_failure_becomes_evidence_text() -> None:
    async def fetch(url: str, max_chars: int):
        raise RuntimeError("timeout")

    builder = SearchContextBuilder(fetch=fetch)
    outcome = await builder.build("总结 https://example.com/article")
    assert outcome.success is False
    assert "链接内容读取失败" in outcome.failure_reason
    assert "timeout" in outcome.failure_reason


@pytest.mark.asyncio
async def test_planner_failure_falls_back_to_raw_user_query() -> None:
    queries = []

    async def search(query: str, num: int):
        queries.append(query)
        return [SearchResult("文档", "https://docs.example.com/item", "预览")]

    async def fetch(url: str, max_chars: int):
        return "网页正文中的确定信息"

    async def verify(user_text, sources, correction_mode, disputed_answer):
        return {
            "status": "supported",
            "claims": [{"text": "信息已核验", "source_ids": ["S1"]}],
        }

    builder = SearchContextBuilder(search=search, fetch=fetch, verifier=verify)
    builder.plan_queries = AsyncMock(return_value=[])
    outcome = await builder.build("查一下 Example SDK 文档")

    assert outcome.success is True
    assert queries
    assert "Example SDK 文档" in queries[0]


@pytest.mark.asyncio
async def test_correction_mode_broadens_and_cross_checks_sources() -> None:
    queries = []

    async def search(query: str, num: int):
        queries.append(query)
        return [
            SearchResult("官方赛果", "https://league.example/result", "A 胜"),
            SearchResult("媒体赛报", "https://news.example/report", "A 胜"),
        ]

    async def fetch(url: str, max_chars: int):
        return "2026年7月15日 A 队以 2:1 获胜的网页正文"

    async def verify(user_text, sources, correction_mode, disputed_answer):
        assert correction_mode is True
        assert "B 队赢了" in disputed_answer
        return {
            "status": "supported",
            "claims": [{"text": "A 队以 2:1 获胜", "source_ids": ["S1", "S2"]}],
            "previous_error": "上一轮把获胜队伍说成了 B 队。",
        }

    history = [
        {"role": "user", "content": "昨天 A 队和 B 队比赛结果"},
        {"role": "assistant", "content": "B 队赢了"},
    ]
    builder = SearchContextBuilder(search=search, fetch=fetch, verifier=verify)
    builder.plan_queries = AsyncMock(return_value=[])
    outcome = await builder.build(
        "不是这个比赛，重新查",
        recent_history=history,
        now=datetime(2026, 7, 16, 9, 0, tzinfo=LOCAL_TZ),
    )

    assert outcome.success is True
    assert outcome.correction_mode is True
    assert len(queries) == 3
    assert len({source.domain for source in outcome.sources}) >= 2
    assert "获胜队伍说成了 B 队" in outcome.previous_error


@pytest.mark.asyncio
async def test_search_preview_without_readable_page_fails_closed() -> None:
    async def search(query: str, num: int):
        return [SearchResult("看似有答案", "https://blocked.example/a", "A 获胜")]

    async def fetch(url: str, max_chars: int):
        return ""

    builder = SearchContextBuilder(search=search, fetch=fetch)
    builder.plan_queries = AsyncMock(return_value=["A 比赛结果"])
    outcome = await builder.build("具体比分是多少")

    assert outcome.required is True
    assert outcome.success is False
    assert not outcome.sources


@pytest.mark.asyncio
async def test_stale_page_is_rejected_for_today_query() -> None:
    async def search(query: str, num: int):
        return [
            SearchResult("旧结果", "https://archive.example/old", "旧页面"),
            SearchResult("官方结果", "https://official.example/current", "今日结果"),
            SearchResult("媒体核验", "https://media.example/current", "今日结果"),
        ]

    async def fetch(url: str, max_chars: int):
        if "archive" in url:
            return "2025年7月16日的旧比赛结果"
        return "2026年7月16日 A 队以 2:1 获胜"

    async def verify(user_text, sources, correction_mode, disputed_answer):
        assert all("archive.example" not in source.url for source in sources)
        return {
            "status": "supported",
            "claims": [{"text": "A 队以 2:1 获胜", "source_ids": ["S1", "S2"]}],
        }

    builder = SearchContextBuilder(search=search, fetch=fetch, verifier=verify)
    builder.plan_queries = AsyncMock(return_value=["今天比赛结果"])
    outcome = await builder.build(
        "今天比赛结果是什么",
        now=datetime(2026, 7, 16, 9, 0, tzinfo=LOCAL_TZ),
    )

    assert outcome.success is True
    assert all("archive.example" not in source.url for source in outcome.sources)
