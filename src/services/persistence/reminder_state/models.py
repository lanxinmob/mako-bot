"""Immutable snapshots for reminder source and scheduler intent compare-and-set."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from src.models.schemas import ReminderRecord


class ReminderPersistenceUnavailable(RuntimeError):
    """No confirmed durable result; never substitute an in-memory scheduler write."""


@dataclass(frozen=True)
class ReminderSnapshot:
    raw: str
    revision: str
    intent_json: str

    @property
    def record(self):
        return ReminderRecord.model_validate_json(self.raw)

    @property
    def intent(self):
        return json.loads(self.intent_json) if self.intent_json else {}

    @property
    def digest(self):
        return hashlib.sha1(self.raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ReminderMutation:
    ok: bool
    code: str
    snapshot: ReminderSnapshot | None
    delivery_state: str
