"""Validate persisted plans and activated tasks before granting a worker lease."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re

from ..state.models import DeliverySpec
from .plans import EffectPlan


@dataclass(frozen=True)
class EffectTask:
    effect_id: str
    kind: str
    codec_version: int
    payload_json: str
    payload_digest: str
    time_basis: str
    state: str
    attempts: int
    lease_token: str
    lease_until_ms: int
    next_attempt_at_ms: int
    result_code: str


@dataclass(frozen=True)
class EffectSnapshot:
    raw: str
    spec: DeliverySpec
    tasks: tuple[EffectTask, ...]


@dataclass(frozen=True)
class EffectLease:
    spec: DeliverySpec
    task: EffectTask


def _integer(value, *, minimum=0):
    if type(value) is not int or not minimum <= value < 2**53:
        raise ValueError("invalid effect counter or time")
    return value


def decode_snapshot(raw, action_id):
    if not isinstance(raw, str) or len(raw.encode()) > 524288:
        raise ValueError("invalid effect action size")
    action = json.loads(raw)
    if not isinstance(action, dict) or action.get("schema_version") != 1:
        raise ValueError("invalid effect action schema")
    if action.get("state") != "sent":
        return None
    spec = DeliverySpec(**json.loads(action["spec_json"]))
    if spec.action_id != action_id or action.get("digest") != spec.digest:
        raise ValueError("effect action identity mismatch")
    if action.get("effects_version") != 1:
        raise ValueError("legacy or unsupported effect plan")
    plan = EffectPlan(action["plan_json"]).validate(spec)
    if plan.digest != action.get("plan_digest") or plan.checksum != action.get("plan_sha1"):
        raise ValueError("effect plan checksum mismatch")
    templates = json.loads(plan.raw)["tasks"]
    tasks = action.get("effects")
    if not isinstance(tasks, list) or len(tasks) != len(templates):
        raise ValueError("incomplete activated effects")
    at = _integer(action.get("sent_recorded_at_ms"), minimum=1)
    origin = action.get("confirmation_source")
    if origin not in {"transport", "owner"}:
        raise ValueError("invalid effect time origin")
    parsed = []
    for value, template in zip(tasks, templates):
        item = EffectTask(**value)
        for name in ("effect_id", "kind", "codec_version"):
            if getattr(item, name) != template[name]:
                raise ValueError("effect task identity mismatch")
        expected = json.loads(template["payload_json"])
        timed = template["time_basis"] == "transport_recorded"
        expected_basis = "unknown" if timed and origin == "owner" else template["time_basis"]
        if timed and origin == "transport":
            expected["sent_at_ms"] = at
        if (item.time_basis != expected_basis or json.loads(item.payload_json) != expected
                or hashlib.sha1(item.payload_json.encode()).hexdigest() != item.payload_digest):
            raise ValueError("activated effect payload mismatch")
        if item.state not in {"pending", "leased", "retry_wait", "complete", "skipped", "needs_review"}:
            raise ValueError("invalid effect task state")
        if timed and origin == "owner" and item.state != "needs_review":
            raise ValueError("owner time remains unresolved")
        _integer(item.attempts)
        _integer(item.lease_until_ms)
        _integer(item.next_attempt_at_ms)
        if (not isinstance(item.lease_token, str)
                or (item.lease_token and re.fullmatch(r"[0-9a-f]{64}", item.lease_token) is None)
                or (item.state == "leased" and not item.lease_token)
                or not isinstance(item.result_code, str) or len(item.result_code) > 64):
            raise ValueError("invalid effect lease metadata")
        parsed.append(item)
    return EffectSnapshot(raw, spec, tuple(parsed))
