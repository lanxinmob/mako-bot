from datetime import date, datetime, timezone

import pytest

from src.core.errors import ExternalServiceError
from src.services.news import (
    TIANXIN_API_BASE,
    extract_tianxin_items,
    news_fingerprint,
    parse_news_datetime,
    select_news,
    yesterday,
)


def test_yesterday_uses_shanghai_calendar_day() -> None:
    now = datetime(2026, 7, 15, 0, 30, tzinfo=timezone.utc)
    assert yesterday(now) == date(2026, 7, 14)


def test_parse_news_datetime_converts_unix_time_to_shanghai() -> None:
    parsed = parse_news_datetime(1784044800)
    assert parsed is not None
    assert parsed.isoformat() == "2026-07-15T00:00:00+08:00"


def test_select_news_keeps_only_yesterday_sorts_and_deduplicates() -> None:
    excluded_item = {
        "title": "already sent",
        "url": "https://example.com/sent",
        "ctime": "2026-07-14 23:00:00",
    }
    items = [
        {"title": "earlier", "url": "https://example.com/early", "ctime": "2026-07-14 08:00:00"},
        {"title": "latest", "url": "https://example.com/latest", "ctime": "2026-07-14 22:00:00"},
        excluded_item,
        {"title": "today", "url": "https://example.com/today", "ctime": "2026-07-15 01:00:00"},
        {"title": "unknown", "url": "https://example.com/unknown"},
        {"title": "duplicate", "url": "https://example.com/latest#comments", "ctime": "2026-07-14 21:00:00"},
    ]

    selected = select_news(
        items,
        target_date=date(2026, 7, 14),
        limit=5,
        excluded={news_fingerprint(excluded_item)},
    )

    assert [item["title"] for item in selected] == ["latest", "earlier"]
    assert all(item["published_at"].startswith("2026-07-14") for item in selected)
    assert all(item["fingerprint"] for item in selected)


def test_tianxin_uses_current_api_domain() -> None:
    assert TIANXIN_API_BASE == "https://apis.tianapi.com"


def test_extract_tianxin_items_reads_new_result_list() -> None:
    payload = {
        "code": 200,
        "msg": "success",
        "result": {"list": [{"title": "news one"}, {"title": "news two"}]},
    }

    assert extract_tianxin_items(payload) == [
        {"title": "news one"},
        {"title": "news two"},
    ]


def test_extract_tianxin_items_rejects_business_error() -> None:
    with pytest.raises(ExternalServiceError, match="code=150"):
        extract_tianxin_items({"code": 150, "msg": "quota exhausted"})
