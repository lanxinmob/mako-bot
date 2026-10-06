"""Redis-only adapter. Call synchronous operations off the application loop."""
from __future__ import annotations

import json
import math
import re
import secrets

from .models import DeliverySpec, DeliveryState, DeliveryUnavailable
from .scripts import TRANSITION


class DeliveryStore:
    def __init__(self, redis_client, *, queued_lease_seconds=30, sending_timeout_seconds=120,
                 require_effects=False):
        self.redis = redis_client
        self.queue_ms = self._milliseconds(queued_lease_seconds)
        self.sending_ms = self._milliseconds(sending_timeout_seconds)
        self.require_effects = require_effects

    @staticmethod
    def _milliseconds(value):
        if not math.isfinite(value) or value < .001:
            raise ValueError("delivery durations must be finite and positive")
        return int(value * 1000)

    @staticmethod
    def key(action_id):
        if not isinstance(action_id, str) or re.fullmatch(r"[0-9a-f]{64}", action_id) is None:
            raise ValueError("invalid delivery action id")
        return f"mako:delivery:v1:{action_id}"

    def _transition(self, operation, action_id, *, token="", spec=None, operator_id="", plan=None):
        key = self.key(action_id)
        if plan is not None:
            plan.validate(spec)
        if self.redis is None:
            raise DeliveryUnavailable("delivery requires Redis")
        try:
            values = self.redis.eval(TRANSITION, 3, key,
                                     spec.source_key if spec and spec.source_key else key,
                                     spec.revision_key if spec and spec.revision_key else key, operation,
                                     spec.digest if spec is not None else "", token,
                                     spec.encode() if spec is not None else "",
                                     self.queue_ms, self.sending_ms, operator_id,
                                     plan.raw if plan is not None else "",
                                     plan.digest if plan is not None else "",
                                     plan.checksum if plan is not None else "",
                                     "yes" if self.require_effects else "no")
            ok, code, state, lease, raw = [v.decode("utf-8") if isinstance(v, bytes) else v
                                         for v in values]
            frozen = DeliverySpec(**json.loads(raw)) if raw else None
            if frozen is not None and frozen.action_id != action_id:
                raise ValueError("delivery identity mismatch")
            return DeliveryState(bool(int(ok)), str(code), str(state),
                                 token if int(ok) else "", int(lease), frozen)
        except Exception as exc:
            raise DeliveryUnavailable("delivery state unavailable; stop sending") from exc

    def claim(self, spec: DeliverySpec, *, plan=None):
        return self._transition("claim", spec.action_id, token=secrets.token_hex(32), spec=spec, plan=plan)

    def recover(self, spec: DeliverySpec, *, plan=None):
        """Claim only an existing unsent record; never recreate lost evidence."""
        return self._transition("recover", spec.action_id, token=secrets.token_hex(32), spec=spec, plan=plan)

    def begin_send(self, spec: DeliverySpec, token: str):
        return self._transition("begin", spec.action_id, token=token, spec=spec)

    def mark_sent(self, action_id, token):
        return self._transition("sent", action_id, token=token)

    def mark_unknown(self, action_id, token):
        return self._transition("unknown", action_id, token=token)

    def reject_before_send(self, action_id, token):
        return self._transition("reject", action_id, token=token)

    def cancel(self, action_id, token):
        return self._transition("cancel", action_id, token=token)

    def inspect(self, action_id):
        return self._transition("inspect", action_id)

    def reconcile(self, action_id, *, delivered, operator_id):
        """Record an authenticated owner's finding, never authorize transport."""
        if type(delivered) is not bool:
            raise ValueError("invalid reconciliation outcome")
        if not isinstance(operator_id, str) or re.fullmatch(r"[0-9]{1,32}", operator_id) is None:
            raise ValueError("invalid reconciliation operator")
        observed = self.inspect(action_id)
        if observed.spec is None:
            return DeliveryState(False, "missing", "", "", 0, None)
        return self._transition("reconcile_sent" if delivered else "reconcile_cancelled",
                                action_id, spec=observed.spec, operator_id=operator_id)
