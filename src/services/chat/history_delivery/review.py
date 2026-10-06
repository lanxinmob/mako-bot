"""Owner-facing metadata never includes chat content, snapshots or tokens."""
import re
from dataclasses import dataclass

from src.services.delivery.state.pagination import parse_cursor
from src.services.persistence.effects import EffectNeedsReview
from src.services.persistence.history_commit.tasks import HistoryEffects
from .discovery import HistoryScanner


@dataclass(frozen=True)
class HistoryEntry:
    action_id: str
    state: str
    bot_id: str = ""
    target: str = ""
    tasks: tuple[tuple[str, str, int, str], ...] = ()
    confirmation_source: str = "transport"


@dataclass(frozen=True)
class HistoryReviewPage:
    next_cursor: str | None
    visited: int
    entries: tuple[HistoryEntry, ...]


def inspect_history(client, action_id: str) -> HistoryEntry:
    try:
        snapshot = HistoryEffects(client).inspect(action_id)
    except EffectNeedsReview:
        return HistoryEntry(action_id, "invalid")
    if snapshot is None:
        return HistoryEntry(action_id, "missing")
    data = snapshot.delivery.plan.data()
    target = (f"group:{data['group_id']}" if data["group_id"] is not None else f"private:{data['user_id']}")
    tasks = tuple((task.kind, task.state, task.attempts, task.result) for task in snapshot.tasks)
    return HistoryEntry(action_id, snapshot.delivery.state, data["bot_id"], target, tasks,
                        snapshot.delivery.confirmation_source)


def list_histories(client, cursor="0:0") -> HistoryReviewPage:
    scan_cursor, offset = parse_cursor(cursor, 10)
    following, keys = HistoryScanner(client)._scan(scan_cursor)
    end = min(len(keys), offset + 10)
    entries = []
    for key in keys[offset:end]:
        match = re.fullmatch(r"mako:chat:delivery:v1:([0-9a-f]{64})", key)
        if match is not None:
            entries.append(inspect_history(client, match[1]))
    next_cursor = (f"{scan_cursor}:{end}" if end < len(keys)
                   else f"{following}:0" if following else None)
    return HistoryReviewPage(next_cursor, max(0, end - offset), tuple(entries))
