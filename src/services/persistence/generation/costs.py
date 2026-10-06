"""Validated immutable cost snapshots and independent retry leases."""
from dataclasses import dataclass
import json
import secrets

from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from ..effects import EffectNeedsReview, EffectUnavailable
from .models import GenerationSpec, decode_attempt, nonnegative, valid_id
from .store import GenerationStore
from .cost_scripts import TRANSITION
from .index_scripts import COST_DUE_KEY


@dataclass(frozen=True)
class CostSnapshot:
    raw: str
    spec: GenerationSpec
    amount: float
    state: str
    token: str


def decode_cost(raw, attempt_id):
    item, spec = decode_attempt(raw, attempt_id)
    if item.get("state") != "completed":
        return None
    amount = nonnegative(json.loads(item["amount_json"]))
    state = item.get("cost_state")
    if state not in {"pending", "leased", "retry_wait", "complete", "needs_review"}:
        raise ValueError("invalid generation cost state")
    if amount == 0 and state != "complete":
        raise ValueError("invalid zero cost state")
    token = item.get("cost_token", "")
    if not isinstance(token, str) or (token and not valid_id(token)):
        raise ValueError("invalid cost lease token")
    if state in {"leased", "retry_wait"} and not token:
        raise ValueError("missing cost lease token")
    required_deadline = {
        "leased": "cost_lease_until_ms",
        "retry_wait": "cost_next_attempt_at_ms",
    }.get(state)
    if required_deadline is not None and required_deadline not in item:
        raise ValueError("missing cost state deadline")
    for name in ("cost_attempts", "cost_lease_until_ms", "cost_next_attempt_at_ms"):
        value = item.get(name, 0)
        if type(value) is not int or not 0 <= value < 2**53:
            raise ValueError("invalid cost lease time or counter")
    return CostSnapshot(raw, spec, float(amount), state, token)


class GenerationCosts:
    def __init__(self, redis_client):
        self.redis = redis_client

    def _read(self, operation):
        if self.redis is None:
            raise EffectUnavailable("generation cost requires Redis")
        try:
            return operation()
        except (EffectUnavailable, EffectNeedsReview):
            raise
        except (RedisConnectionError, RedisTimeoutError, ConnectionError, TimeoutError) as exc:
            raise EffectUnavailable("generation cost outcome unavailable") from exc
        except Exception as exc:
            raise EffectNeedsReview("generation cost requires review") from exc

    def inspect(self, attempt_id):
        key = GenerationStore.key(attempt_id)

        def read():
            raw = self.redis.get(key)
            if raw is None:
                return None
            return decode_cost(raw.decode() if isinstance(raw, bytes) else raw, attempt_id)

        return self._read(read)

    def _transition(self, snapshot, operation, token, outcome=""):
        def run():
            raw = self.redis.eval(TRANSITION, 2, GenerationStore.key(snapshot.spec.attempt_id),
                                  COST_DUE_KEY, snapshot.raw, operation, token, outcome,
                                  snapshot.spec.attempt_id)
            raw = raw.decode() if isinstance(raw, bytes) else raw
            if raw == "index_unconfirmed":
                raise EffectUnavailable("generation cost saved; index update unconfirmed")
            if raw == "":
                return None
            return decode_cost(raw, snapshot.spec.attempt_id)
        return self._read(run)

    def claim(self, attempt_id):
        snapshot = self.inspect(attempt_id)
        if snapshot is None or snapshot.state not in {"pending", "leased", "retry_wait"}:
            return None
        return self._transition(snapshot, "claim", secrets.token_hex(32))

    def finish(self, lease, outcome):
        if outcome not in {"applied", "already_applied", "unavailable", "conflict", "needs_review"}:
            raise ValueError("invalid cost outcome")
        current = self.inspect(lease.spec.attempt_id)
        if current is None or current.spec != lease.spec or current.amount != lease.amount:
            return False
        return self._transition(current, "finish", lease.token, outcome) is not None
