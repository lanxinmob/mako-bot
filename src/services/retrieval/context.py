"""Search orchestration with explicit dependency injection."""
from __future__ import annotations
from datetime import datetime
from typing import List, Optional
from .formatting import (
    LOCAL_TZ,
    MAX_SEARCH_RESULTS,
    MAX_SEARCH_QUERIES,
    MAX_SEARCH_CANDIDATES,
    MAX_PAGE_EVIDENCE_CHARS,
    MAX_URL_CONTEXT_CHARS,
    _previous_turn,
)

from dataclasses import replace
from typing import Awaitable, Callable
from urllib.parse import urlsplit
from src.services.retrieval.client import SearchResult
from src.services.retrieval.client import web_search
from src.services.retrieval.client import fetch_page_text
from . import (
    dependencies,
    planning,
    ranking,
    verification,
)
from .models import SearchOutcome, SearchSource, VerifiedClaim
from .planning import (
    normalize_search_queries,
    needs_strict_fact_check,
    query_with_time_hint,
    query_with_image_hint,
    _date_targets,
)

class SearchContextBuilder:
    def __init__(
        self,
        *,
        search: Callable[..., Awaitable[List[SearchResult]]] = web_search,
        fetch: Callable[..., Awaitable[str]] = fetch_page_text,
        dependencies=dependencies,
        verifier: Optional[
            Callable[[str, List[SearchSource], bool, str], Awaitable[dict]]
        ] = None,
    ) -> None:
        self._deps = dependencies
        self.search = search
        self.fetch = fetch
        self.verifier = verifier


    async def build(
        self,
        user_text: str,
        *,
        image_context: str = "",
        recent_history: Optional[List[dict]] = None,
        now: Optional[datetime] = None,
    ) -> SearchOutcome:
        history = recent_history or []
        current = now or datetime.now(LOCAL_TZ)
        correction_mode = self._deps.is_correction_request(user_text)
        decisions = self._deps.decide_intents(
            user_text, has_image=bool(image_context), has_audio=False, face_ids=[]
        )
        relevant = [
            item
            for item in decisions
            if item.name in {"search.web", "search.summarize_url"}
        ][:2]
        self._deps.search_metrics.record_routing(
            expected_search=self._deps.is_dynamic_fact_query(user_text) or correction_mode,
            routed_to_search=bool(relevant or correction_mode),
        )
        if not relevant and not correction_mode:
            return SearchOutcome()

        started = self._deps.time.perf_counter()
        if relevant and relevant[0].name == "search.summarize_url":
            return await self._build_url_summary(relevant[0].args.get("url", ""), started)

        strict = needs_strict_fact_check(user_text) or correction_mode
        minimum_domains = 2 if strict else 1
        planned = await self.plan_queries(
            user_text,
            image_context=image_context,
            recent_history=history,
            correction_mode=correction_mode,
        )
        queries = planned or self._fallback_queries(
            user_text, history, correction_mode=correction_mode
        )
        if correction_mode and len(queries) < MAX_SEARCH_QUERIES:
            fallback = self._fallback_queries(user_text, history, correction_mode=True)
            queries = normalize_search_queries([*queries, *fallback])
        if not queries:
            return self._finalize(
                SearchOutcome(
                    required=True,
                    attempted=False,
                    correction_mode=correction_mode,
                    realtime=strict,
                    route_reason="correction" if correction_mode else "search_intent",
                    failure_reason="检索规划失败，原始查询也为空",
                ),
                started,
            )

        hinted_queries = [
            query_with_time_hint(query_with_image_hint(query, image_context), current)
            for query in queries
        ]
        search_batches = await self._deps.asyncio.gather(
            *(self._search_one(query) for query in hinted_queries)
        )
        errors = [error for _, error in search_batches if error]
        candidates: list[SearchResult] = []
        seen_urls: set[str] = set()
        for results, _ in search_batches:
            for result in results:
                key = (result.link or "").strip().lower()
                if not key or key in seen_urls:
                    continue
                seen_urls.add(key)
                candidates.append(result)
        candidates = candidates[:MAX_SEARCH_CANDIDATES]
        if not candidates:
            provider_unavailable = bool(errors) and len(errors) == len(search_batches)
            reason = "；".join(errors[:2]) or "搜索提供器没有返回结果"
            return self._finalize(
                SearchOutcome(
                    required=True,
                    attempted=True,
                    correction_mode=correction_mode,
                    realtime=strict,
                    route_reason="correction" if correction_mode else "search_intent",
                    queries=tuple(hinted_queries),
                    failure_reason=reason,
                    provider_unavailable=provider_unavailable,
                    search_calls=len(hinted_queries),
                ),
                started,
            )

        fetched = await self._deps.asyncio.gather(
            *(self._fetch_one(item.link) for item in candidates)
        )
        sources = self._rank_sources(
            candidates,
            fetched,
            hinted_queries,
            date_targets=_date_targets(" ".join((user_text, *hinted_queries)), current),
        )
        domain_count = len({source.domain for source in sources})
        if not sources or domain_count < minimum_domains:
            return self._finalize(
                SearchOutcome(
                    required=True,
                    attempted=True,
                    correction_mode=correction_mode,
                    realtime=strict,
                    route_reason="correction" if correction_mode else "search_intent",
                    queries=tuple(hinted_queries),
                    sources=tuple(sources),
                    failure_reason=(
                        f"只取得 {domain_count} 个可读取的独立来源，至少需要 {minimum_domains} 个"
                    ),
                    search_calls=len(hinted_queries),
                    page_fetches=len(candidates),
                ),
                started,
            )

        _, disputed_answer = _previous_turn(history)
        verification = await self._verify(
            user_text,
            sources,
            correction_mode=correction_mode,
            disputed_answer=disputed_answer,
        )
        claims = self._parse_claims(verification, sources)
        status = str(verification.get("status") or "").lower()
        cited_domains = {
            source.domain
            for source in sources
            if any(source.source_id in claim.source_ids for claim in claims)
        }
        if status != "supported" or not claims or len(cited_domains) < minimum_domains:
            reason = str(verification.get("reason") or "").strip()
            if status == "conflicting":
                reason = reason or "不同来源存在无法消解的冲突"
            else:
                reason = reason or "证据核验没有形成可支持的结论"
            return self._finalize(
                SearchOutcome(
                    required=True,
                    attempted=True,
                    correction_mode=correction_mode,
                    realtime=strict,
                    route_reason="correction" if correction_mode else "search_intent",
                    queries=tuple(hinted_queries),
                    sources=tuple(sources),
                    failure_reason=reason,
                    search_calls=len(hinted_queries),
                    page_fetches=len(candidates),
                ),
                started,
            )

        previous_error = str(verification.get("previous_error") or "").strip()
        if correction_mode and not previous_error:
            previous_error = "上一轮把尚未交叉核验的事实当成了确定结论，该答案已标记失效。"
        return self._finalize(
            SearchOutcome(
                required=True,
                attempted=True,
                success=True,
                factual_mode=True,
                realtime=strict,
                correction_mode=correction_mode,
                route_reason="correction" if correction_mode else "search_intent",
                queries=tuple(hinted_queries),
                sources=tuple(sources),
                claims=tuple(claims),
                previous_error=previous_error,
                search_calls=len(hinted_queries),
                page_fetches=len(candidates),
            ),
            started,
        )


    async def _build_url_summary(self, url: str, started: float) -> SearchOutcome:
        if not url:
            return self._finalize(
                SearchOutcome(required=True, failure_reason="链接为空"), started
            )
        try:
            page = await self.fetch(url, max_chars=MAX_URL_CONTEXT_CHARS)
        except Exception as exc:
            page = ""
            reason = f"链接内容读取失败：{exc}"
        else:
            reason = "链接内容为空或无法读取" if not page else ""
        if not page:
            return self._finalize(
                SearchOutcome(
                    required=True,
                    attempted=True,
                    failure_reason=f"{reason}：{url}",
                    page_fetches=1,
                ),
                started,
            )
        domain = (urlsplit(url).hostname or "unknown").lower()
        source = SearchSource("S1", url, url, domain, "", page, 1.0)
        return self._finalize(
            SearchOutcome(
                required=True,
                attempted=True,
                success=True,
                factual_mode=True,
                route_reason="summarize_url",
                sources=(source,),
                claims=(VerifiedClaim("仅总结该网页正文，不补充网页外事实。", ("S1",)),),
                page_fetches=1,
            ),
            started,
        )


    async def _search_one(self, query: str) -> tuple[List[SearchResult], str]:
        try:
            return await self.search(query, num=MAX_SEARCH_RESULTS), ""
        except Exception as exc:
            self._deps.logger.warning(f"联网搜索失败 query={query}: {exc}")
            return [], str(exc)


    async def _fetch_one(self, url: str) -> str:
        try:
            return await self.fetch(url, max_chars=MAX_PAGE_EVIDENCE_CHARS)
        except Exception as exc:
            self._deps.logger.warning(f"搜索结果正文读取失败 url={url}: {exc}")
            return ""


    def _finalize(self, outcome: SearchOutcome, started: float) -> SearchOutcome:
        return finalize(outcome, started, dependencies=self._deps)


    # Explicit bound entry points preserve instance-level replacement in callers.
    plan_queries = planning.plan_queries
    _fallback_queries = planning._fallback_queries
    _rank_sources = ranking._rank_sources
    _verify = verification._verify
    _parse_claims = staticmethod(verification._parse_claims)


def finalize(outcome: SearchOutcome, started: float, *, dependencies=dependencies) -> SearchOutcome:
    latency_ms = (dependencies.time.perf_counter() - started) * 1000
    cost_per_call = max(0.0, getattr(dependencies.get_settings(), "search_cost_per_call", 0.0))
    finished = replace(
        outcome,
        latency_ms=round(latency_ms, 2),
        estimated_cost=round(outcome.search_calls * cost_per_call, 6),
    )
    dependencies.search_metrics.record_pipeline(
        attempted=finished.attempted,
        evidence_success=finished.success,
        correction_mode=finished.correction_mode,
        correction_recovered=finished.correction_mode and finished.success,
        provider_unavailable=finished.provider_unavailable,
        fail_closed=finished.required and not finished.success,
        search_calls=finished.search_calls,
        page_fetches=finished.page_fetches,
        estimated_cost=finished.estimated_cost,
        latency_ms=finished.latency_ms,
    )
    dependencies.logger.info("搜索链路指标 {}", dependencies.search_metrics.snapshot())
    return finished
