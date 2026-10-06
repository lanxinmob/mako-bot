"""Read-only discovery of unverified old followups and retained reminders."""
from __future__ import annotations

from dataclasses import dataclass
import re

from src.models.schemas import RelationshipMemory, ReminderRecord
from src.services.persistence.followups import revision_key
from src.services.persistence.reminder_state import REVISION_KEY
from .models import DeliveryUnavailable
from .pagination import parse_cursor


@dataclass(frozen=True)
class LegacyEntry:
    business_id: str
    status: str
    target: str = ""
    due_at: str = ""


@dataclass(frozen=True)
class LegacyPage:
    entries: tuple[LegacyEntry, ...]
    next_cursor: str | None


def _arguments(client, cursor, limit):
    first, offset = parse_cursor(cursor, limit)
    if client is None:
        raise DeliveryUnavailable("legacy inspection requires Redis")
    return first, offset


def _text(value):
    return value.decode("utf-8") if isinstance(value, bytes) else value


def list_old_followups(client, cursor="0:0", *, limit=10):
    """Read quarantine then the original index, including not-yet-quarantined work.

    Rank pagination is advisory on changing indexes; it is never a send claim.
    No index migration, status update or new revision occurs here.
    """
    stage, offset = _arguments(client, cursor, limit)
    if stage not in (0, 1):
        raise ValueError("invalid followup listing stage")
    key = "mako:delivery:v1:legacy:followups" if stage == 0 else "relationship:followups"
    try:
        members = client.zrange(key, offset, offset + limit)
        following = (f"{stage}:{offset + limit}" if len(members) > limit
                     else "1:0" if stage == 0 else None)
        rows = []
        for raw_member in members[:limit]:
            member = _text(raw_member)
            match = re.fullmatch(r"([0-9]{1,32}):([A-Za-z0-9_-]{1,512})", member)
            if not match:
                rows.append(LegacyEntry(member[:80], "invalid_index"))
                continue
            user, memory_id = int(match[1]), match[2]
            raw = client.hget(f"relationship:{user}", memory_id)
            revision = client.hget(revision_key(user), memory_id)
            if revision:
                continue
            if raw is None:
                rows.append(LegacyEntry(member, "missing_source"))
                continue
            try:
                memory = RelationshipMemory.model_validate_json(raw)
                if memory.user_id != user or memory.memory_id != memory_id:
                    raise ValueError("identity mismatch")
            except Exception:
                rows.append(LegacyEntry(member, "invalid_source"))
                continue
            status = "legacy_unverified" if memory.status == "active" and memory.due_at else "stale_index"
            rows.append(LegacyEntry(member, status, f"private:{user}",
                                    memory.due_at.isoformat() if memory.due_at else ""))
        return LegacyPage(tuple(rows), following)
    except Exception as exc:
        raise DeliveryUnavailable("legacy followup listing unavailable") from exc


def list_retained_reminders(client, cursor="0:0", *, limit=10):
    """Show unversioned and overdue records without migrating or deleting them."""
    scan_cursor, offset = _arguments(client, cursor, limit)
    try:
        following, values = client.hscan("reminders", cursor=scan_cursor, count=limit)
        items = sorted((_text(key), raw) for key, raw in values.items())
        end = min(len(items), offset + limit)
        next_cursor = (f"{scan_cursor}:{end}" if end < len(items)
                       else f"{int(following)}:0" if int(following) else None)
        seconds, micros = client.time()
        now = seconds + micros / 1000000
        rows = []
        for job_id, raw in items[offset:end]:
            try:
                reminder = ReminderRecord.model_validate_json(raw)
                if reminder.reminder_id != job_id:
                    raise ValueError("identity mismatch")
            except Exception:
                rows.append(LegacyEntry(job_id[:80], "invalid_source"))
                continue
            revision = client.hget(REVISION_KEY, job_id)
            overdue = reminder.remind_time.timestamp() <= now
            if revision and not overdue:
                continue
            status = "legacy_unverified" if not revision else "overdue_check_action"
            rows.append(LegacyEntry(job_id, status, f"group:{reminder.group_id}",
                                    reminder.remind_time.isoformat()))
        return LegacyPage(tuple(rows), next_cursor)
    except Exception as exc:
        raise DeliveryUnavailable("retained reminder listing unavailable") from exc
