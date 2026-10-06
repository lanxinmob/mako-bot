"""Freeze complete history evidence and transport identity before sending."""
import base64
from dataclasses import dataclass
import hashlib
import json

from ..generation.models import valid_id
from .snapshot import HistorySnapshot, decode_history


MAX_PLAN_BYTES = 1048576
# Redis cjson uses at most 14 significant digits. Keep persisted numeric
# timestamps exact without changing the approved integer wire format.
MAX_TIMESTAMP_MS = 99999999999999


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def integer(value, minimum=0) -> int:
    if type(value) is not int or not minimum <= value < 2**53:
        raise ValueError("invalid frozen history integer")
    return value


def timestamp_ms(value) -> int:
    integer(value, 1)
    if value > MAX_TIMESTAMP_MS:
        raise ValueError("history time exceeds exact JSON capacity")
    return value


@dataclass(frozen=True)
class HistoryDeliveryPlan:
    raw: str

    def __post_init__(self):
        if not isinstance(self.raw, str) or len(self.raw.encode("utf-8")) > MAX_PLAN_BYTES:
            raise ValueError("history plan exceeds serialized capacity")
        data = json.loads(self.raw)
        fields = {"version", "action_id", "bot_id", "user_id", "group_id", "snapshot",
                  "text", "history", "max_history_turns", "global_max_records", "utc_offset_seconds"}
        if not isinstance(data, dict) or set(data) != fields or type(data["version"]) is not int or data["version"] != 1:
            raise ValueError("invalid history plan schema")
        if not valid_id(data["action_id"]):
            raise ValueError("invalid history delivery identity")
        bot_id = data["bot_id"]
        if not isinstance(bot_id, str) or not bot_id.isascii() or not bot_id.isdigit():
            raise ValueError("invalid history bot identity")
        integer(int(bot_id), 1)
        user_id = integer(data["user_id"], 1)
        group_id = None if data["group_id"] is None else integer(data["group_id"], 1)
        if not isinstance(data["text"], str) or not data["text"]:
            raise ValueError("invalid frozen reply")
        turns = integer(data["max_history_turns"], 1)
        retention = integer(data["global_max_records"], 1000)
        if turns > 2**31 - 1 or retention > 2**31 - 1:
            raise ValueError("invalid frozen history retention")
        offset = data["utc_offset_seconds"]
        if type(offset) is not int or not -86399 <= offset <= 86399:
            raise ValueError("invalid frozen history time offset")
        snapshot = data["snapshot"]
        if not isinstance(snapshot, dict) or set(snapshot) != {"session_id", "source", "raw_base64"}:
            raise ValueError("invalid frozen history snapshot")
        raw = snapshot["raw_base64"]
        evidence = None if raw is None else base64.b64decode(raw.encode("ascii"), validate=True)
        frozen = HistorySnapshot(snapshot["session_id"], snapshot["source"], evidence)
        expected = f"group_{group_id}" if group_id is not None else f"private_{user_id}"
        if frozen.session_id != expected:
            raise ValueError("history plan target mismatch")
        history = decode_history(canonical(data["history"]).encode("utf-8"))
        if len(history) > turns * 2:
            raise ValueError("history plan exceeds frozen retention")
        if canonical(data) != self.raw:
            raise ValueError("noncanonical history plan")

    @property
    def action_id(self) -> str:
        return self.data()["action_id"]

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.raw.encode("utf-8")).hexdigest()

    def data(self) -> dict:
        return json.loads(self.raw)

    def snapshot(self) -> HistorySnapshot:
        data = self.data()["snapshot"]
        raw = data["raw_base64"]
        return HistorySnapshot(data["session_id"], data["source"],
                               None if raw is None else base64.b64decode(raw, validate=True))

    def effect_id(self, kind: str) -> str:
        if kind not in {"session", "global"}:
            raise ValueError("invalid history effect kind")
        return hashlib.sha256(("chat-history-v1:" + self.action_id + ":" + kind).encode()).hexdigest()


def build_plan(action_id: str, snapshot: HistorySnapshot, *, bot_id: str,
               user_id: int, group_id: int | None, text: str, history: list[dict],
               max_history_turns: int, global_max_records: int,
               utc_offset_seconds: int) -> HistoryDeliveryPlan:
    if not isinstance(snapshot, HistorySnapshot) or not isinstance(history, list):
        raise ValueError("history plan requires a durable snapshot and messages")
    integer(max_history_turns, 1)
    return HistoryDeliveryPlan(canonical({
        "version": 1, "action_id": action_id, "bot_id": bot_id,
        "user_id": user_id, "group_id": group_id, "text": text,
        "snapshot": {"session_id": snapshot.session_id, "source": snapshot.source,
                     "raw_base64": None if snapshot.raw is None else base64.b64encode(snapshot.raw).decode("ascii")},
        "history": history[-max_history_turns * 2:],
        "max_history_turns": max_history_turns, "global_max_records": global_max_records,
        "utc_offset_seconds": utc_offset_seconds,
    }))
