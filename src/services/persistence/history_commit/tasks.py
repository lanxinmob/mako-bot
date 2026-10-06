"""Independent history leases require a permanent acknowledged delivery."""
from dataclasses import dataclass
import json
import secrets

from ..effects import EffectNeedsReview
from ..generation.models import valid_id
from .delivery import HistoryDeliverySnapshot, HistoryDeliveryStore, decode_delivery
from .plans import HistoryDeliveryPlan, MAX_TIMESTAMP_MS, integer
from .task_scripts import TRANSITION


OUTCOMES = {"applied", "already_applied", "history_conflict", "conflict",
            "target_incomplete", "invalid_payload", "execution_error"}


@dataclass(frozen=True)
class HistoryTask:
    kind: str
    state: str
    attempts: int = 0
    token: str = ""
    lease_until_ms: int = 0
    next_attempt_at_ms: int = 0
    result: str = ""


@dataclass(frozen=True)
class HistoryEffectSnapshot:
    delivery: HistoryDeliverySnapshot
    tasks: tuple[HistoryTask, ...]


@dataclass(frozen=True)
class HistoryLease:
    plan: HistoryDeliveryPlan
    delivered_at_ms: int
    task: HistoryTask


def decode_tasks(delivery: HistoryDeliverySnapshot) -> HistoryEffectSnapshot:
    data = json.loads(delivery.raw)
    metadata = data.get("task_meta", {})
    if not isinstance(metadata, dict) or not set(metadata) <= {"session", "global"}:
        raise ValueError("invalid history task metadata")
    if delivery.confirmation_source == "owner":
        # Manual confirmation provides no actual ACK time and cannot activate work.
        result = "time_unconfirmed" if delivery.state == "sent" else ""
        tasks = tuple(HistoryTask(kind, state, result=result) for kind, state in data["tasks"].items())
        return HistoryEffectSnapshot(delivery, tasks)
    tasks = []
    for kind, state in data["tasks"].items():
        value = metadata.get(kind)
        if kind not in metadata:
            if state not in {"pending", "dormant"}:
                raise ValueError("missing history task metadata")
            tasks.append(HistoryTask(kind, state))
            continue
        if not isinstance(value, dict) or set(value) != {
            "attempts", "token", "lease_until_ms", "next_attempt_at_ms", "result"
        }:
            raise ValueError("invalid history task schema")
        task = HistoryTask(kind, state, **value)
        if (not valid_id(task.token) or not 1 <= integer(task.attempts) <= 2**31 - 1
                or state in {"pending", "dormant"} or not isinstance(task.result, str)):
            raise ValueError("invalid history lease identity")
        for deadline in (task.lease_until_ms, task.next_attempt_at_ms):
            if integer(deadline) > MAX_TIMESTAMP_MS:
                raise ValueError("invalid history lease deadline")
        if (state == "leased" and (task.lease_until_ms == 0 or task.next_attempt_at_ms != 0 or task.result)
                or state == "retry_wait" and (task.lease_until_ms != 0 or task.next_attempt_at_ms == 0
                                               or task.result != "unavailable")
                or state in {"complete", "needs_review"} and
                (task.lease_until_ms != 0 or task.next_attempt_at_ms != 0)):
            raise ValueError("inconsistent history lease state")
        expected = {"applied", "already_applied"} if state == "complete" else OUTCOMES - {"applied", "already_applied"}
        if state in {"complete", "needs_review"} and task.result not in expected:
            raise ValueError("invalid history task result")
        tasks.append(task)
    return HistoryEffectSnapshot(delivery, tuple(tasks))


class HistoryEffects:
    def __init__(self, redis_client, *, lease_seconds=120):
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 3600:
            raise ValueError("invalid history lease duration")
        self.store = HistoryDeliveryStore(redis_client)
        self.redis = redis_client
        self.lease_ms = lease_seconds * 1000

    def inspect(self, action_id: str) -> HistoryEffectSnapshot | None:
        def read():
            delivery = self.store.inspect(action_id)
            return None if delivery is None else decode_tasks(delivery)
        return self.store._read(read)

    def _transition(self, snapshot, kind, operation, token, outcome=""):
        def run():
            delivery = snapshot.delivery
            raw = self.redis.eval(TRANSITION, 1, self.store.key(delivery.plan.action_id),
                                  delivery.raw, kind, operation, token, self.lease_ms, outcome)
            raw = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            if raw == "":
                return None
            result = decode_tasks(decode_delivery(raw, delivery.plan.action_id))
            task = next(task for task in result.tasks if task.kind == kind)
            if task.token != token:
                raise EffectNeedsReview("invalid history lease transition response")
            return HistoryLease(result.delivery.plan, result.delivery.delivered_at_ms, task)
        return self.store._read(run)

    def claim(self, action_id: str, kind: str) -> HistoryLease | None:
        if kind not in {"session", "global"}:
            raise ValueError("invalid history effect kind")
        snapshot = self.inspect(action_id)
        if (snapshot is None or snapshot.delivery.state != "sent"
                or snapshot.delivery.confirmation_source != "transport"):
            return None
        task = next(task for task in snapshot.tasks if task.kind == kind)
        if task.state not in {"pending", "leased", "retry_wait"}:
            return None
        lease = self._transition(snapshot, kind, "claim", secrets.token_hex(32))
        if lease is not None and lease.task.state != "leased":
            raise EffectNeedsReview("invalid history claim response")
        return lease

    def _settle(self, lease: HistoryLease, operation: str, outcome: str) -> bool:
        if not isinstance(lease, HistoryLease) or lease.task.state != "leased" or not valid_id(lease.task.token):
            raise ValueError("invalid history effect lease")
        snapshot = self.inspect(lease.plan.action_id)
        if (snapshot is None or snapshot.delivery.state != "sent"
                or snapshot.delivery.confirmation_source != "transport"
                or snapshot.delivery.plan != lease.plan
                or snapshot.delivery.delivered_at_ms != lease.delivered_at_ms):
            return False
        return self._transition(snapshot, lease.task.kind, operation, lease.task.token, outcome) is not None

    def finish(self, lease: HistoryLease, outcome: str) -> bool:
        if outcome not in OUTCOMES:
            raise ValueError("invalid history effect outcome")
        return self._settle(lease, "finish", outcome)

    def defer(self, lease: HistoryLease) -> bool:
        return self._settle(lease, "defer", "unavailable")
