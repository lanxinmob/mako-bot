"""Verified retrieval evidence contracts."""
from __future__ import annotations
from dataclasses import dataclass
from .formatting import build_time_context, truncate_search_text

@dataclass(frozen=True)
class VerifiedClaim:
    text: str
    source_ids: tuple[str, ...]


@dataclass(frozen=True)
class SearchSource:
    source_id: str
    title: str
    url: str
    domain: str
    snippet: str
    page_text: str
    score: float = 0.0


@dataclass(frozen=True)
class SearchOutcome:
    required: bool = False
    attempted: bool = False
    success: bool = False
    factual_mode: bool = False
    realtime: bool = False
    correction_mode: bool = False
    route_reason: str = ""
    queries: tuple[str, ...] = ()
    sources: tuple[SearchSource, ...] = ()
    claims: tuple[VerifiedClaim, ...] = ()
    previous_error: str = ""
    failure_reason: str = ""
    provider_unavailable: bool = False
    search_calls: int = 0
    page_fetches: int = 0
    latency_ms: float = 0.0
    estimated_cost: float = 0.0

    def context_text(self) -> str:
        if not self.required:
            return ""
        lines = [
            "[联网事实核验]",
            f"状态：{'已核验' if self.success else '失败，禁止猜测'}",
            f"模式：{'纠错' if self.correction_mode else '事实回答'}",
            f"时间上下文：{build_time_context()}",
        ]
        if self.queries:
            lines.extend(("查询：", *[f"- {query}" for query in self.queries]))
        if not self.success:
            lines.append(f"失败原因：{self.failure_reason or '没有取得足够可靠证据'}")
            lines.append("回答约束：不得根据常识、记忆或上一轮答案补全事实。")
            return "\n".join(lines)
        if self.correction_mode:
            lines.append(
                "上一轮错误："
                + (self.previous_error or "上一轮事实结论未通过本轮重新核验，现已失效。")
            )
        lines.append("已核验结论：")
        for claim in self.claims:
            refs = " ".join(f"[{source_id}]" for source_id in claim.source_ids)
            lines.append(f"- {claim.text} {refs}".rstrip())
        lines.append("可引用来源（网页正文已打开并读取）：")
        for source in self.sources:
            lines.append(
                f"- [{source.source_id}] {source.title}\n"
                f"  URL: {source.url}\n"
                f"  正文摘录: {truncate_search_text(source.page_text, 900)}"
            )
        lines.append(
            "回答约束：只回答上面的已核验结论；每个实时事实都使用对应的 "
            "[S编号](URL) 行内引用；不得把搜索摘要当成网页正文。"
        )
        return "\n".join(lines)
