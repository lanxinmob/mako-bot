from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, List, Optional
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import httpx

from src.core.config import get_settings
from src.core.errors import ExternalServiceError


LOCAL_TZ = ZoneInfo("Asia/Shanghai")
_DATE_FIELDS = ("ctime", "pubdate", "pubDate", "publish_time", "published_at", "date", "time")
TIANXIN_API_BASE = "https://apis.tianapi.com"


def yesterday(now: Optional[datetime] = None) -> date:
    current = now or datetime.now(LOCAL_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=LOCAL_TZ)
    return current.astimezone(LOCAL_TZ).date() - timedelta(days=1)


def parse_news_datetime(value: object) -> Optional[datetime]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().isdigit()):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp /= 1000
        try:
            return datetime.fromtimestamp(timestamp, tz=timezone.utc).astimezone(LOCAL_TZ)
        except (OSError, OverflowError, ValueError):
            return None
    elif isinstance(value, str):
        raw = value.strip().replace("Z", "+00:00")
        parsed = None
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d"):
                try:
                    parsed = datetime.strptime(raw, pattern)
                    break
                except ValueError:
                    continue
        if parsed is None:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=LOCAL_TZ)
    return parsed.astimezone(LOCAL_TZ)


def _published_at(item: dict) -> Optional[datetime]:
    for field in _DATE_FIELDS:
        parsed = parse_news_datetime(item.get(field))
        if parsed is not None:
            return parsed
    return None


def _canonical_url(value: object) -> str:
    url = str(value or "").strip()
    if not url or url == "#":
        return ""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), parts.query, ""))


def news_fingerprint(item: dict) -> str:
    identity = _canonical_url(item.get("url")) or str(item.get("title", "")).strip().casefold()
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def select_news(
    items: Iterable[dict],
    *,
    target_date: date,
    limit: int,
    excluded: Optional[set[str]] = None,
) -> List[dict]:
    excluded = excluded or set()
    selected: list[tuple[datetime, dict]] = []
    seen: set[str] = set()
    for item in items:
        published_at = _published_at(item)
        if published_at is None or published_at.date() != target_date:
            continue
        normalized = dict(item)
        normalized["published_at"] = published_at.isoformat()
        fingerprint = news_fingerprint(normalized)
        if not normalized.get("title") or fingerprint in excluded or fingerprint in seen:
            continue
        normalized["fingerprint"] = fingerprint
        seen.add(fingerprint)
        selected.append((published_at, normalized))
    selected.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in selected[: max(0, limit)]]


def extract_tianxin_items(payload: object) -> list[dict]:
    if not isinstance(payload, dict):
        raise ExternalServiceError("TianAPI returned a non-object response")
    code = payload.get("code")
    if code != 200:
        message = str(payload.get("msg") or "unknown error")
        raise ExternalServiceError(f"TianAPI request failed: code={code} msg={message}")
    result = payload.get("result")
    if isinstance(result, dict):
        items = result.get("list", [])
    elif isinstance(result, list):
        items = result
    else:
        items = []
    if not isinstance(items, list):
        raise ExternalServiceError("TianAPI result.list is not an array")
    return [item for item in items if isinstance(item, dict)]


async def fetch_juejin(
    limit: int = 2,
    *,
    target_date: Optional[date] = None,
    excluded: Optional[set[str]] = None,
) -> List[dict]:
    url = "https://api.juejin.cn/recommend_api/v1/article/recommend_all_feed"
    payload = {"client_type": 2608, "cursor": "0", "id_type": 2, "limit": 50, "sort_type": 200}
    async with httpx.AsyncClient(timeout=20.0) as client:
        rep = await client.post(url, json=payload, headers={"User-Agent": "Mozilla/5.0"})
        rep.raise_for_status()
        data = rep.json().get("data", [])
    articles: List[dict] = []
    for item in data:
        if item.get("item_type") != 2:
            continue
        info = item.get("item_info", {}).get("article_info", {})
        articles.append(
            {
                "title": info.get("title", ""),
                "description": info.get("brief_content", "..."),
                "url": f"https://juejin.cn/post/{info.get('article_id', '')}",
                "ctime": info.get("ctime"),
            }
        )
    return select_news(articles, target_date=target_date or yesterday(), limit=limit, excluded=excluded)


async def fetch_tianxin(
    api_name: str,
    limit: int = 2,
    *,
    target_date: Optional[date] = None,
    excluded: Optional[set[str]] = None,
) -> List[dict]:
    key = get_settings().tianxin_key
    if not key:
        return []
    url = f"{TIANXIN_API_BASE}/{api_name}/index"
    async with httpx.AsyncClient(timeout=20.0) as client:
        rep = await client.post(
            url,
            data={"key": key, "num": 50, "page": 1, "rand": 0, "form": 1},
        )
        rep.raise_for_status()
        data = extract_tianxin_items(rep.json())
    items = [
        {
            "title": item.get("title", ""),
            "description": item.get("description", "N/A"),
            "url": item.get("url", ""),
            "ctime": item.get("ctime"),
            "pubdate": item.get("pubdate"),
        }
        for item in data
    ]
    return select_news(items, target_date=target_date or yesterday(), limit=limit, excluded=excluded)
