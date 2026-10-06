"""Bounded action inspection pages; SCAN is not a snapshot or a send authority."""
from __future__ import annotations

from dataclasses import dataclass
import re

from .models import DeliveryUnavailable
from .store import DeliveryStore
from .pagination import parse_cursor


@dataclass(frozen=True)
class DeliveryEntry:
    action_id: str
    state: str
    kind: str = ""
    target: str = ""


@dataclass(frozen=True)
class DeliveryPage:
    entries: tuple[DeliveryEntry, ...]
    next_cursor: str | None


def list_delivery_page(client, cursor="0:0", *, limit=10):
    """At most limit record inspections and rows, with no whole-keyspace loop.

    COUNT is a Redis work hint, not a hard bound on returned keys. The offset
    resumes an oversized batch by rescanning its input cursor. On a changing
    keyspace pages can repeat or omit entries; restart from 0:0 for a new pass.
    No record is removed, and page contents never authorize transport.
    """
    scan_cursor, offset = parse_cursor(cursor, limit)
    if client is None:
        raise DeliveryUnavailable("delivery listing requires Redis")
    try:
        following, raw_keys = client.scan(cursor=scan_cursor, match="mako:delivery:v1:*", count=limit)
        keys = sorted(key.decode("utf-8") if isinstance(key, bytes) else key for key in raw_keys)
    except Exception as exc:
        raise DeliveryUnavailable("delivery listing unavailable") from exc
    end = min(len(keys), offset + limit)
    next_cursor = (f"{scan_cursor}:{end}" if end < len(keys)
                   else f"{int(following)}:0" if int(following) else None)
    store, entries = DeliveryStore(client), []
    for key in keys[offset:end]:
        action = re.fullmatch(r"mako:delivery:v1:([0-9a-f]{64})", key)
        if not action:
            continue  # Revision/intent hashes are not execution records.
        action_id = action[1]
        try:
            result = store.inspect(action_id)
        except DeliveryUnavailable:
            entries.append(DeliveryEntry(action_id, "unavailable"))
            continue
        spec = result.spec
        entries.append(DeliveryEntry(action_id, result.state or "missing",
            spec.kind if spec else "", f"{spec.target_type}:{spec.target_id}" if spec else ""))
    return DeliveryPage(tuple(entries), next_cursor)
