from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import List, Optional

from nonebot.log import logger

from src.core.config import get_settings
from src.core.errors import NotConfiguredError
from src.services.http import fetch_json, fetch_text


@dataclass
class SearchResult:
    title: str
    link: str
    snippet: str


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
            )
        )
    return results


def extract_text_from_html(content: str) -> str:
    content = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", content)
    content = re.sub(r"(?is)<.*?>", " ", content)
    content = html.unescape(content)
    content = re.sub(r"\s+", " ", content).strip()
    return content


async def fetch_page_text(url: str, max_chars: int = 6000) -> str:
    try:
        html_text = await fetch_text(url)
    except Exception as exc:
        logger.warning(f"Failed to fetch url content: {exc}")
        return ""
    text = extract_text_from_html(html_text)
    if len(text) > max_chars:
        return text[:max_chars]
    return text


def extract_urls(text: str) -> List[str]:
    return re.findall(r"https?://[^\s]+", text)
