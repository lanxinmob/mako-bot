from __future__ import annotations

import asyncio
import html
import ipaddress
import re
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import urlsplit, urlunsplit

from nonebot.log import logger

from src.core.config import get_settings
from src.core.errors import NotConfiguredError, UnsafeUrlError
from src.services.http import fetch_json, fetch_text


@dataclass
class SearchResult:
    title: str
    link: str
    snippet: str
    source: str = ""
    score: float = 0.0


def _truncate(text: str, max_len: int) -> str:
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if len(text) <= max_len:
        return text
    return text[:max_len].rstrip() + "..."


def _url_key(url: str) -> str:
    try:
        parsed = urlsplit(url)
    except Exception:
        return url.strip()
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, parsed.query, ""))


def _address_is_public(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return bool(address.is_global)


async def validate_public_url(url: str) -> str:
    """Reject local, private, credential-bearing and non-HTTP fetch targets."""

    try:
        parsed = urlsplit((url or "").strip())
    except ValueError as exc:
        raise UnsafeUrlError("URL 格式无效") from exc
    if parsed.scheme.lower() not in {"http", "https"}:
        raise UnsafeUrlError("只允许 http/https URL")
    if not parsed.hostname or parsed.username or parsed.password:
        raise UnsafeUrlError("URL 缺少主机名或包含凭据")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise UnsafeUrlError("不允许访问本机地址")
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None
    if literal is not None:
        if not literal.is_global:
            raise UnsafeUrlError("不允许访问非公网 IP")
    else:
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(
                hostname,
                parsed.port or (443 if parsed.scheme.lower() == "https" else 80),
                type=0,
            )
        except OSError as exc:
            raise UnsafeUrlError("域名解析失败") from exc
        addresses = {item[4][0].split("%", 1)[0] for item in infos if item[4]}
        if not addresses or any(not _address_is_public(item) for item in addresses):
            raise UnsafeUrlError("域名解析到了非公网地址")
    return parsed.geturl()


def _dedupe_and_limit(results: List[SearchResult], limit: int) -> List[SearchResult]:
    seen: set[str] = set()
    cleaned: List[SearchResult] = []
    for item in results:
        if not item.link:
            continue
        key = _url_key(item.link)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(
            SearchResult(
                title=_truncate(item.title or "Untitled", 160),
                link=item.link.strip(),
                snippet=_truncate(item.snippet, 420),
                source=_truncate(item.source, 80),
                score=item.score,
            )
        )
        if len(cleaned) >= limit:
            break
    return cleaned


async def google_search(query: str, num: Optional[int] = None) -> List[SearchResult]:
    settings = get_settings()
    if not settings.google_api_key or not settings.google_cx:
        raise NotConfiguredError("Google Custom Search is not configured.")
    count = num or settings.google_result_count
    data = await fetch_json(
        "https://www.googleapis.com/customsearch/v1",
        params={"key": settings.google_api_key, "cx": settings.google_cx, "q": query, "num": count},
    )
    items = data.get("items", [])
    results: List[SearchResult] = []
    for item in items:
        results.append(
            SearchResult(
                title=item.get("title", "Untitled"),
                link=item.get("link", ""),
                snippet=item.get("snippet", ""),
                source="google",
            )
        )
    return _dedupe_and_limit(results, count)


async def searxng_search(query: str, num: Optional[int] = None) -> List[SearchResult]:
    settings = get_settings()
    if not settings.searxng_base_url:
        raise NotConfiguredError("SEARXNG_BASE_URL is not configured.")

    limit = num or settings.searxng_result_count
    data = await fetch_json(
        settings.searxng_base_url.rstrip("/") + "/search",
        params={"q": query, "format": "json"},
        timeout=25.0,
    )
    raw_items = data.get("results", [])
    results: List[SearchResult] = []
    for item in raw_items:
        engines = item.get("engines")
        if isinstance(engines, list) and engines:
            source = ",".join(str(engine) for engine in engines[:3])
        else:
            source = str(item.get("engine") or "searxng")
        try:
            score = float(item.get("score") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        results.append(
            SearchResult(
                title=item.get("title") or "Untitled",
                link=item.get("url") or item.get("link") or "",
                snippet=item.get("content") or item.get("snippet") or "",
                source=source,
                score=score,
            )
        )
    return _dedupe_and_limit(results, limit)


async def web_search(query: str, num: Optional[int] = None) -> List[SearchResult]:
    settings = get_settings()
    if settings.search_provider == "searxng":
        return await searxng_search(query, num=num)
    return await google_search(query, num=num)


def extract_text_from_html(content: str) -> str:
    content = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", content)
    content = re.sub(r"(?is)<.*?>", " ", content)
    content = html.unescape(content)
    content = re.sub(r"\s+", " ", content).strip()
    return content


async def fetch_page_text(url: str, max_chars: int = 6000) -> str:
    try:
        safe_url = await validate_public_url(url)
        html_text = await fetch_text(safe_url)
    except Exception as exc:
        logger.warning(f"Failed to fetch url content: {exc}")
        return ""
    text = extract_text_from_html(html_text)
    if len(text) > max_chars:
        return text[:max_chars]
    return text


def extract_urls(text: str) -> List[str]:
    return re.findall(r"https?://[^\s]+", text)
