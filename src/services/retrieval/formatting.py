"""Time, bounded evidence text, and legacy history formatting."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from src.services.chat.policy import compact_text

LOCAL_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


MAX_IMAGES_TO_DESCRIBE = 3


MAX_SEARCH_RESULTS = 5


MAX_SEARCH_QUERIES = 3


MAX_SEARCH_CANDIDATES = 8


MAX_VERIFIED_SOURCES = 5


MAX_SEARCH_SNIPPET_CHARS = 240


MAX_PAGE_EVIDENCE_CHARS = 3600


MAX_URL_CONTEXT_CHARS = 5000


def build_time_context(now: Optional[datetime] = None) -> str:
    current = now or datetime.now(LOCAL_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=LOCAL_TZ)
    today = current.date()
    return (
        f"当前时间：{current.strftime('%Y-%m-%d %H:%M:%S %Z')}；"
        f"今天={today.isoformat()}；昨天={(today - timedelta(days=1)).isoformat()}；"
        f"明天={(today + timedelta(days=1)).isoformat()}。"
    )


def _history_content(message: dict) -> str:
    if message.get("invalidated"):
        return "[该事实回答已失效]"
    content = str(message.get("content", ""))
    # Clean legacy histories written before search context was separated.
    for marker in ("\n\n[联网搜索结果]", "\n\n[联网事实核验]"):
        content = content.split(marker, 1)[0]
    return content


def compact_recent_history(
    history: List[dict], max_turns: int = 6, max_chars: int = 900
) -> str:
    lines: List[str] = []
    for message in history[-max_turns:]:
        content = compact_text(_history_content(message), 180)
        if content:
            lines.append(f"{message.get('role', 'unknown')}: {content}")
    return compact_text("\n".join(lines), max_chars)


def _previous_turn(history: List[dict]) -> tuple[str, str]:
    previous_user = ""
    previous_assistant = ""
    for message in reversed(history):
        role = message.get("role")
        if role == "assistant" and not previous_assistant:
            previous_assistant = _history_content(message)
        elif role == "user" and not previous_user:
            previous_user = _history_content(message)
        if previous_user and previous_assistant:
            break
    return previous_user, previous_assistant


def truncate_search_text(text: str, max_chars: int = MAX_SEARCH_SNIPPET_CHARS) -> str:
    compact = " ".join((text or "").split())
    return compact if len(compact) <= max_chars else compact[:max_chars].rstrip() + "..."
