"""Redis-only reminder source API; APScheduler is deliberately absent."""
from __future__ import annotations

import json
import re
import uuid

from .models import ReminderMutation, ReminderPersistenceUnavailable, ReminderSnapshot
from .scripts import TRANSITION

REVISION_KEY = "mako:delivery:v1:source:reminder"
INTENT_KEY = "mako:delivery:v1:reminder:intents"


class ReminderStateStore:
    def __init__(self, redis_client):
        self.redis = redis_client

    def _call(self, operation, job_id, *, snapshot=None, record=None, bot_id="", grace=60, action_key=""):
        if not isinstance(job_id, str) or not job_id or len(job_id) > 512:
            raise ValueError("invalid reminder id")
        if action_key and re.fullmatch(r"mako:delivery:v1:[0-9a-f]{64}", action_key) is None:
            raise ValueError("invalid delivery action key")
        if self.redis is None:
            raise ReminderPersistenceUnavailable("reminder changes require Redis")
        payload = json.dumps(record.model_dump(mode="json"), ensure_ascii=False, sort_keys=True) if record else ""
        due = int(record.remind_time.timestamp() * 1000) if record else ""
        try:
            values = self.redis.eval(TRANSITION, 4, "reminders", REVISION_KEY, INTENT_KEY,
                action_key or "mako:delivery:v1:no-action", operation, job_id,
                snapshot.raw if snapshot else "", snapshot.revision if snapshot else "",
                payload, uuid.uuid4().hex, bot_id, due, grace, "yes" if action_key else "no")
            ok, code, raw, revision, intent, phase = [v.decode("utf-8") if isinstance(v, bytes) else v for v in values]
            current = ReminderSnapshot(raw, revision, intent) if raw else None
            if current is not None and current.record.reminder_id != job_id:
                raise ValueError("reminder identity mismatch")
            return ReminderMutation(bool(int(ok)), code, current, phase)
        except Exception as exc:
            raise ReminderPersistenceUnavailable("reminder persistence outcome unavailable") from exc

    def load(self, job_id):
        return self._call("load", job_id).snapshot

    def scan_ids(self, cursor=0, *, intents=False, count=100):
        """Read one recovery page, without authorizing any send.

        Scan both sources and intents in separate passes: cancelled sources no
        longer exist, while legacy sources do not yet have scheduler intents.
        HSCAN COUNT is a work hint, not a hard page limit. Callers must accept
        empty nonterminal pages, duplicates and changes between pages, and load
        each current snapshot before scheduling. Never use scan data as a CAS.
        """
        if type(cursor) is not int or cursor < 0:
            raise ValueError("invalid scan cursor")
        if type(count) is not int or not 1 <= count <= 1000:
            raise ValueError("invalid scan count")
        if type(intents) is not bool:
            raise ValueError("invalid scan source")
        if self.redis is None:
            raise ReminderPersistenceUnavailable("reminder recovery requires Redis")
        try:
            following, entries = self.redis.hscan(
                INTENT_KEY if intents else "reminders", cursor=cursor, count=count)
            ids = tuple(key.decode("utf-8") if isinstance(key, bytes) else key
                        for key in entries)
            if any(not isinstance(key, str) or not key or len(key) > 512 for key in ids):
                raise ValueError("invalid persisted reminder id")
            return int(following), ids
        except Exception as exc:
            raise ReminderPersistenceUnavailable("reminder recovery page unavailable") from exc

    def create(self, record, *, bot_id):
        if not isinstance(bot_id, str) or not bot_id:
            raise ValueError("new reminders require a bot identity")
        return self._call("create", record.reminder_id, record=record, bot_id=bot_id)

    def replace(self, snapshot, record, *, bot_id, action_key=""):
        old = snapshot.record
        if (record.reminder_id, record.session_id, record.group_id, record.user_id) != (
                old.reminder_id, old.session_id, old.group_id, old.user_id):
            raise ValueError("reminder replacement cannot change identity or owner")
        if not isinstance(bot_id, str) or not bot_id:
            raise ValueError("replacement requires a bot identity")
        return self._call("replace", old.reminder_id, snapshot=snapshot, record=record,
                          bot_id=bot_id, action_key=action_key)

    def migrate_future(self, snapshot):
        return self._call("migrate", snapshot.record.reminder_id, snapshot=snapshot,
                          record=snapshot.record, grace=300)

    def bind_bot(self, snapshot, bot_id):
        if not isinstance(bot_id, str) or not bot_id:
            raise ValueError("invalid bot identity")
        return self._call("bind", snapshot.record.reminder_id, snapshot=snapshot, bot_id=bot_id)

    def cancel(self, snapshot, *, action_key=""):
        return self._call("cancel", snapshot.record.reminder_id, snapshot=snapshot, action_key=action_key)

    def complete(self, snapshot, *, action_key):
        return self._call("complete", snapshot.record.reminder_id, snapshot=snapshot, action_key=action_key)
