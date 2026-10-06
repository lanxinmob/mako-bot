"""Lease, finish and defer post-delivery tasks without authorizing transport."""
from __future__ import annotations

import json
import secrets

from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from src.services.persistence.effects import EffectNeedsReview, EffectUnavailable
from ..state.store import DeliveryStore
from .models import EffectLease, EffectTask, decode_snapshot
from .scripts import TRANSITION


_RETRY_ERRORS = (RedisConnectionError, RedisTimeoutError, ConnectionError, TimeoutError)
_OUTCOMES = {"applied", "already_applied", "superseded", "cancelled", "missing",
             "inconsistent", "wrong_action", "conflict", "execution_error", "invalid_payload", "target_incomplete"}


class EffectStore:
    def __init__(self, redis_client, *, lease_seconds=120):
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 3600:
            raise ValueError("invalid effect lease duration")
        self.redis = redis_client
        self.lease_ms = lease_seconds * 1000

    def inspect(self, action_id):
        key = DeliveryStore.key(action_id)
        if self.redis is None:
            raise EffectUnavailable("effect tasks require Redis")
        try:
            raw = self.redis.get(key)
            if raw is None:
                return None
            raw = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            return decode_snapshot(raw, action_id)
        except _RETRY_ERRORS as exc:
            raise EffectUnavailable("effect tasks unavailable") from exc
        except Exception as exc:
            raise EffectNeedsReview("effect action requires review") from exc

    def _transition(self, snapshot, task, operation, token, outcome=""):
        try:
            values = self.redis.eval(TRANSITION, 1, DeliveryStore.key(snapshot.spec.action_id),
                snapshot.raw, task.effect_id, task.payload_digest, operation, token, self.lease_ms, outcome)
            ok, _, raw = [v.decode("utf-8") if isinstance(v, bytes) else v for v in values]
            if int(ok) == 0:
                return None
            return EffectTask(**json.loads(raw))
        except _RETRY_ERRORS as exc:
            raise EffectUnavailable("effect lease outcome unavailable") from exc
        except Exception as exc:
            raise EffectNeedsReview("effect lease transition requires review") from exc

    def claim(self, action_id, effect_id):
        snapshot = self.inspect(action_id)
        if snapshot is None:
            return None
        task = next((item for item in snapshot.tasks if item.effect_id == effect_id), None)
        if task is None:
            return None
        claimed = self._transition(snapshot, task, "claim", secrets.token_hex(32))
        return EffectLease(snapshot.spec, claimed) if claimed is not None else None

    def _settle(self, lease, operation, outcome):
        snapshot = self.inspect(lease.spec.action_id)
        if snapshot is None or snapshot.spec != lease.spec:
            return False
        task = next((item for item in snapshot.tasks if item.effect_id == lease.task.effect_id), None)
        if task is None or task.payload_digest != lease.task.payload_digest:
            return False
        return self._transition(snapshot, task, operation, lease.task.lease_token, outcome) is not None

    def finish(self, lease, outcome):
        if outcome not in _OUTCOMES:
            raise ValueError("invalid effect outcome")
        return self._settle(lease, "finish", outcome)

    def defer(self, lease):
        return self._settle(lease, "defer", "unavailable")
