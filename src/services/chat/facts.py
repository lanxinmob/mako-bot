"""Generation phase of the chat pipeline.

``ChatEngine`` is transport agnostic: it receives a fully enriched request and
returns a reply plus the history that should be committed after delivery.  The
NoneBot adapter owns sending, so a failed send is never recorded as successful.
"""

from __future__ import annotations

from typing import List

from nonebot.log import logger

from src.services.retrieval.models import SearchOutcome
from src.services.delivery.reminder import extract_json_object



def search_failure_reply(outcome: SearchOutcome) -> str:
    prefix = "上一轮事实答案已标记失效。" if outcome.correction_mode else ""
    reason = outcome.failure_reason or "没有取得足够可靠的网页证据"
    return (
        f"{prefix}这次联网核验失败：{reason}。"
        "为避免继续给出错误的实时事实，我不会根据记忆或猜测补答案。"
    )


def ensure_source_links(text: str, outcome: SearchOutcome) -> str:
    if any(source.url in text for source in outcome.sources):
        return text
    links = "、".join(
        f"[{source.source_id}]({source.url})" for source in outcome.sources[:3]
    )
    return f"{text.rstrip()}\n\n来源：{links}" if links else text


def verified_fallback_answer(outcome: SearchOutcome) -> str:
    if not outcome.claims:
        return ""
    sources = {source.source_id: source for source in outcome.sources}
    lines: List[str] = []
    if outcome.correction_mode:
        lines.append(
            "上一轮错误："
            + (outcome.previous_error or "上一轮事实答案没有经过充分核验。")
        )
    lines.append("重新核验后的结论：" if outcome.correction_mode else "核验结论：")
    for claim in outcome.claims:
        refs = "、".join(
            f"[{source_id}]({sources[source_id].url})"
            for source_id in claim.source_ids
            if source_id in sources
        )
        lines.append(f"- {claim.text} {refs}".rstrip())
    return "\n".join(lines)


async def validate_factual_answer(
    call_llm,
    user_text: str,
    answer: str,
    outcome: SearchOutcome,
) -> bool:
    claims = "\n".join(
        f"- {claim.text} sources={','.join(claim.source_ids)}"
        for claim in outcome.claims
    )
    urls = "\n".join(
        f"{source.source_id}={source.url}" for source in outcome.sources
    )
    evidence = "\n".join(
        f"{source.source_id}正文摘录={source.page_text[:1200]}"
        for source in outcome.sources
    )
    prompt = f"""
检查候选回答是否完全受已核验结论支持，是否混入额外事实，以及实时事实引用是否只指向允许的 URL。
如果这是纠错模式，还必须检查回答是否明确说明了上一轮具体错在哪里。
只返回 JSON：{{"consistent":true|false,"reason":"原因"}}

用户问题：{user_text}
纠错模式：{'是' if outcome.correction_mode else '否'}
上一轮错误：{outcome.previous_error or '无'}
已核验结论：
{claims}
允许引用：
{urls}
网页正文证据：
{evidence}
候选回答：
{answer}
"""
    try:
        raw, _ = await call_llm(
            [{"role": "user", "content": prompt}], max_tokens=300
        )
        data = extract_json_object(raw)
        return bool(data and data.get("consistent") is True)
    except Exception as exc:
        logger.warning(f"事实回答一致性检查失败: {exc}")
        return False
