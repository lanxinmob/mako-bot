"""Frozen, content-free identity and pricing for one provider invocation."""
from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
import math
import re


def valid_id(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def nonnegative(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError("invalid generation cost or rate")
    return value


@dataclass(frozen=True)
class GenerationSpec:
    attempt_id: str
    user_id: int
    phase: str
    model: str
    input_digest: str
    cost_day: str
    input_rate: float
    output_rate: float
    estimated_cost: float

    def __post_init__(self):
        if not valid_id(self.attempt_id) or not valid_id(self.input_digest):
            raise ValueError("invalid generation identity")
        if type(self.user_id) is not int or not 0 <= self.user_id < 2**53:
            raise ValueError("invalid generation user")
        if self.phase not in {"reply", "fact_check"}:
            raise ValueError("invalid generation phase")
        if not isinstance(self.model, str) or not self.model.strip() or len(self.model) > 128:
            raise ValueError("invalid generation model")
        if not isinstance(self.cost_day, str) or re.fullmatch(r"[0-9]{8}", self.cost_day) is None:
            raise ValueError("invalid generation date")
        datetime.strptime(self.cost_day, "%Y%m%d")
        for value in (self.input_rate, self.output_rate, self.estimated_cost):
            nonnegative(value)

    def encode(self):
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"), allow_nan=False)

    @property
    def cost_effect_id(self):
        return hashlib.sha256(("generation-cost-v1:" + self.attempt_id).encode()).hexdigest()


def decode_attempt(raw, attempt_id):
    """Apply the same identity/time checks to review and automatic consumers."""
    if not isinstance(raw, str) or len(raw.encode()) > 16384:
        raise ValueError("invalid generation evidence size")
    item = json.loads(raw)
    if not isinstance(item, dict) or type(item.get("schema_version")) is not int or item["schema_version"] != 1:
        raise ValueError("invalid generation schema")
    spec = GenerationSpec(**json.loads(item["spec_json"]))
    if spec.attempt_id != attempt_id or not valid_id(item.get("token")):
        raise ValueError("invalid generation identity")
    started = item.get("started_at_ms")
    if type(started) is not int or not 0 < started < 2**53:
        raise ValueError("invalid generation start time")
    state = item.get("state")
    if state != "completed":
        expected = {"calling": "not_ready", "unknown": "needs_review"}
        if state not in expected or item.get("cost_state") != expected[state] or "amount_json" in item:
            raise ValueError("invalid unresolved generation state")
    return item, spec
