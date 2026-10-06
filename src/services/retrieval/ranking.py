"""Readable source selection and domain diversity ranking."""
from __future__ import annotations
from datetime import date
from typing import List
from .formatting import MAX_VERIFIED_SOURCES, truncate_search_text

import re
from urllib.parse import urlsplit
from src.services.retrieval.client import SearchResult
from .models import SearchSource

def _contains_date(text: str, target: date) -> bool:
    full_variants = (
        target.isoformat(),
        target.strftime("%Y/%m/%d"),
        f"{target.year}年{target.month}月{target.day}日",
    )
    if any(value in text for value in full_variants):
        return True
    has_explicit_year_date = bool(
        re.search(r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b", text)
        or re.search(r"\d{4}年\d{1,2}月\d{1,2}日", text)
    )
    return not has_explicit_year_date and f"{target.month}月{target.day}日" in text


def _query_terms(queries: List[str]) -> set[str]:
    terms: set[str] = set()
    for query in queries:
        terms.update(re.findall(r"[A-Za-z0-9_-]{3,}|[\u4e00-\u9fff]{2,}", query.lower()))
    return terms


def _rank_sources(
    self,
    candidates: List[SearchResult],
    pages: List[str],
    queries: List[str],
    *,
    date_targets: tuple[date, ...],
) -> List[SearchSource]:
    terms = _query_terms(queries)
    ranked: list[tuple[float, SearchResult, str, str]] = []
    for result, page in zip(candidates, pages):
        if not page.strip():
            continue
        domain = (urlsplit(result.link).hostname or "unknown").lower().removeprefix("www.")
        combined = f"{result.title} {result.snippet} {page}".lower()
        if date_targets and not all(_contains_date(combined, target) for target in date_targets):
            self._deps.logger.info("过滤疑似陈旧网页 url={} targets={}", result.link, date_targets)
            continue
        overlap = sum(1 for term in terms if term in combined)
        score = float(result.score or 0.0) + overlap * 0.25 + min(len(page), 3000) / 3000
        ranked.append((score, result, page, domain))
    ranked.sort(key=lambda item: item[0], reverse=True)

    selected: list[tuple[float, SearchResult, str, str]] = []
    used_domains: set[str] = set()
    for item in ranked:
        if item[3] in used_domains:
            continue
        selected.append(item)
        used_domains.add(item[3])
        if len(selected) >= MAX_VERIFIED_SOURCES:
            break
    if len(selected) < MAX_VERIFIED_SOURCES:
        for item in ranked:
            if item in selected:
                continue
            selected.append(item)
            if len(selected) >= MAX_VERIFIED_SOURCES:
                break
    return [
        SearchSource(
            source_id=f"S{index}",
            title=truncate_search_text(result.title, 160),
            url=result.link,
            domain=domain,
            snippet=truncate_search_text(result.snippet),
            page_text=page,
            score=round(score, 3),
        )
        for index, (score, result, page, domain) in enumerate(selected, start=1)
    ]
