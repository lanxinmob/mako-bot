"""Generation phase of the chat pipeline.

``ChatEngine`` is transport agnostic: it receives a fully enriched request and
returns a reply plus the history that should be committed after delivery.  The
NoneBot adapter owns sending, so a failed send is never recorded as successful.
"""

from __future__ import annotations

from typing import List




from .models import ChatRequest

def next_history(request: ChatRequest, reply_text: str) -> List[dict]:
    history: List[dict] = []
    for item in request.history:
        role = item.get("role")
        if role not in {"user", "assistant"}:
            continue
        cleaned = dict(item)
        cleaned["content"] = strip_legacy_enrichment(
            str(item.get("content", ""))
        )
        history.append(cleaned)
    if request.search_outcome.correction_mode:
        for item in reversed(history):
            if item.get("role") == "assistant":
                item["invalidated"] = True
                item["invalidated_reason"] = "user_correction"
                break
    assistant: dict = {"role": "assistant", "content": reply_text}
    if request.search_outcome.required:
        assistant["factual_answer"] = True
        assistant["search_status"] = (
            "verified" if request.search_outcome.success else "fail_closed"
        )
    return history + [
        {
            "role": "user",
            "content": request.user_text,
        },
        assistant,
    ]


def strip_legacy_enrichment(content: str) -> str:
    for marker in (
        "\n\n[图片识别结果]",
        "\n\n[联网搜索结果]",
        "\n\n[联网事实核验]",
        "\n\n[工具执行结果]",
    ):
        content = content.split(marker, 1)[0]
    return content


def history_for_prompt(request: ChatRequest) -> List[dict]:
    messages: List[dict] = []
    disputed_replaced = False
    for item in reversed(request.history):
        role = item.get("role")
        if role not in {"user", "assistant"}:
            continue
        invalidated = bool(item.get("invalidated"))
        if (
            request.search_outcome.correction_mode
            and role == "assistant"
            and not disputed_replaced
        ):
            invalidated = True
            disputed_replaced = True
        content = strip_legacy_enrichment(
            str(item.get("content", ""))
        )
        if invalidated:
            content = "[上一轮事实回答已失效，不得作为当前事实依据。]"
        messages.append({"role": role, "content": content})
    messages.reverse()
    return messages
