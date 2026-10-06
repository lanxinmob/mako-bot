from datetime import datetime
from typing import Optional


def parse_datetime(value: object) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None

def optional_int(value: object) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

def normalize_progress_event_kind(event_type: str) -> str:
    if event_type in {
        "created",
        "updated",
        "blocked",
        "completed",
        "cancelled",
        "note",
        "decision",
        "sent",
        "ask_owner",
        "rejected",
        "approved",
        "rewritten",
        "silent",
    }:
        return event_type
    if "approve" in event_type or "批准" in event_type:
        return "approved"
    if "cancel" in event_type or "取消" in event_type:
        return "cancelled"
    if "rewrite" in event_type or "改写" in event_type:
        return "rewritten"
    if "ask" in event_type or "owner" in event_type:
        return "ask_owner"
    if "sent" in event_type or "send" in event_type:
        return "sent"
    if "silent" in event_type:
        return "silent"
    if "decision" in event_type:
        return "decision"
    return "note"

def normalize_trace_kind(trace_type: str) -> str:
    if trace_type in {"chat", "tool", "autonomy", "system"}:
        return trace_type
    if trace_type.startswith("autonomy") or trace_type.startswith("decision"):
        return "autonomy"
    if trace_type.startswith("tool"):
        return "tool"
    return "chat"
