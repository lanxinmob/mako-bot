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


async def ollama_search(query: str, num: Optional[int] = None) -> List[SearchResult]:
    settings = get_settings()
    if not settings.ollama_api_key:
        raise NotConfiguredError("OLLAMA_API_KEY is not configured.")

    count = min(max(num or settings.ollama_search_result_count, 1), 10)
    data = await fetch_json(
        "https://ollama.com/api/web_search",
        json_data={"query": query, "max_results": count},
        headers={
            "Authorization": f"Bearer {settings.ollama_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
        timeout=25.0,
    )
    items = data.get("results", [])
    results: List[SearchResult] = []
    for item in items:
        results.append(
            SearchResult(
                title=item.get("title") or "Untitled",
                link=item.get("url") or "",
                snippet=item.get("content") or "",
                source="ollama",
            )
        )
    return _dedupe_and_limit(results, count)


async def web_search(query: str, num: Optional[int] = None) -> List[SearchResult]:
    return await ollama_search(query, num=num)


async def ollama_fetch_page(url: str) -> str:
    settings = get_settings()
    if not settings.ollama_api_key:
        raise NotConfiguredError("OLLAMA_API_KEY is not configured.")

    data = await fetch_json(
        "https://ollama.com/api/web_fetch",
        json_data={"url": url},
        headers={
            "Authorization": f"Bearer {settings.ollama_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
        timeout=30.0,
    )
    return str(data.get("content") or "").strip()


def extract_text_from_html(content: str) -> str:
    content = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", content)
    content = re.sub(r"(?is)<.*?>", " ", content)
    content = html.unescape(content)
    content = re.sub(r"\s+", " ", content).strip()
    return content


async def fetch_page_text(url: str, max_chars: int = 6000) -> str:
    try:
        safe_url = await validate_public_url(url)
    except Exception as exc:
        logger.warning(
            "Page URL validation failed url={} error_type={} error={}",
            url,
            type(exc).__name__,
            exc,
        )
        return ""

    try:
        text = await ollama_fetch_page(safe_url)
        if not text:
            raise ValueError("Ollama web_fetch returned empty content")
    except Exception as ollama_exc:
        logger.warning(
            "Ollama web_fetch failed url={} error_type={} error={}",
            safe_url,
            type(ollama_exc).__name__,
            ollama_exc,
        )
        try:
            html_text = await fetch_text(
                safe_url,
                validate_redirect=validate_public_url,
            )
            text = extract_text_from_html(html_text)
        except Exception as local_exc:
            logger.warning(
                "Local page fetch failed url={} error_type={} error={}",
                safe_url,
                type(local_exc).__name__,
                local_exc,
            )
            return ""

    return text[:max_chars]


def extract_urls(text: str) -> List[str]:
    return re.findall(r"https?://[^\s]+", text)
