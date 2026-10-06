"""Translation, language detection, web search and URL summaries."""
from __future__ import annotations

from typing import Awaitable, Callable

from src.services.tools.intent import IntentDecision

from .dependencies import ToolDependencies
from .models import ToolExecutionResult


async def handle(
    decision: IntentDecision, result: ToolExecutionResult, text: str, *,
    summarize_text: Callable[[str], Awaitable[str]], dependencies: ToolDependencies,
) -> bool:
    name = decision.name
    args = decision.args

    if name == "language.translate":
        translated = await dependencies.translate_text(args.get("text", text), args.get("target_lang", "ZH"))
        result.fact_lines.append(f"翻译结果: {translated}")
        return True

    if name == "language.detect":
        lang = dependencies.detect_language(args.get("text", text))
        result.fact_lines.append(f"语种识别结果: {lang}")
        return True

    if name == "search.web":
        query = args.get("query", text)
        items = await dependencies.web_search(query, num=5)
        if not items:
            result.fact_lines.append("搜索结果为空。")
            return True
        lines = [
            f"- {item.title}\n  {item.link}\n  来源: {item.source or 'search'}\n  {item.snippet}"
            for item in items[:5]
        ]
        result.fact_lines.append("联网搜索结果:\n" + "\n".join(lines))
        return True

    if name == "search.summarize_url":
        url = args.get("url", "")
        page_text = await dependencies.fetch_page_text(url)
        if not page_text:
            result.fact_lines.append("链接总结失败: 网页内容为空。")
            return True
        summary = await summarize_text(page_text[:3500])
        result.fact_lines.append(f"链接总结（{url}）: {summary}")
        return True

    return False


async def summarize_text(text: str, *, dependencies: ToolDependencies) -> str:
    prompt = "请用中文在120字内总结以下网页内容并保留关键事实:\n" + text
    if dependencies.has_deepseek():
        client = dependencies.get_deepseek_client()
        response = await client.chat.completions.create(
            model=dependencies.get_deepseek_model(),
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=300,
        )
        return (response.choices[0].message.content or "").strip()
    if dependencies.has_openai():
        client = dependencies.get_openai_client()
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=300,
        )
        return (response.choices[0].message.content or "").strip()
    return text[:120]
