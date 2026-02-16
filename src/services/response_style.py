from __future__ import annotations

import re


def sanitize_persona_reply(reply: str, *, directed: bool, max_undirected_chars: int) -> str:
    text = (reply or "").strip()
    if not text:
        return "茉子大人正在思考，稍后再聊。"

    forbidden = [
        "作为AI",
        "作为一个AI",
        "我是AI",
        "语言模型",
        "无法提供帮助",
    ]
    for token in forbidden:
        text = text.replace(token, "茉子大人")

    # Keep group non-directed replies compact to mimic human conversational rhythm.
    if not directed and len(text) > max_undirected_chars:
        split = re.split(r"[。！？!?]", text)
        head = split[0].strip() if split else text
        text = head[:max_undirected_chars].rstrip() + "。"
    return text.strip()
