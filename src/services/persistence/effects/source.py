"""Version-bound source completion with permanent effect receipts.

These targets require a sent action with a matching embedded task. An unfinished
target receipt prohibits replay, even if the earlier error response was lost.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import re
from typing import TYPE_CHECKING

from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from .source_scripts import PREFIX
from .store import EffectConflict, EffectIncomplete, EffectNeedsReview, EffectUnavailable

if TYPE_CHECKING:
    from src.services.delivery.state.models import DeliverySpec


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def source_effect_id(spec: DeliverySpec) -> str:
    """Stable semantic occurrence; independent of retries and lease tokens."""
    return hashlib.sha256(_canonical([spec.action_id, spec.kind + "_complete", 0]).encode()).hexdigest()


def source_payload(spec: DeliverySpec) -> str:
    return _canonical({"action_id": spec.action_id, "spec_digest": spec.digest})


def _source_keys(spec):
    if not re.fullmatch(r"0|[1-9][0-9]{0,19}", spec.target_id):
        raise ValueError("invalid source target")
    if not spec.revision or not re.fullmatch(r"[0-9a-f]{40}", spec.source_digest):
        raise ValueError("invalid source version binding")
    if spec.kind == "followup" and spec.target_type == "private":
        keys = (f"relationship:{spec.target_id}",
                f"mako:delivery:v1:source:followup:{spec.target_id}", "relationship:followups")
    elif spec.kind == "reminder" and spec.target_type == "group":
        keys = ("reminders", "mako:delivery:v1:source:reminder", "mako:delivery:v1:reminder:intents")
    else:
        raise ValueError("unsupported source completion")
    if (spec.source_key != keys[0] or spec.revision_key != keys[1]
            or spec.source_field != spec.business_id):
        raise ValueError("source keys do not match business identity")
    return keys


def validate_source_spec(spec: DeliverySpec) -> None:
    """Validate a plan's source binding before any transport is authorized."""
    _source_keys(spec)


class SourceEffectWriter:
    def __init__(self, redis_client):
        self.redis = redis_client

    def complete_effect(self, effect_id: str, spec: DeliverySpec) -> str:
        keys = _source_keys(spec)
        if effect_id != source_effect_id(spec):
            raise ValueError("invalid source effect identity")
        if self.redis is None:
            raise EffectUnavailable("source effects require Redis")
        # Domain modules are separate from the shared authorization and receipt
        # protocol, and never receive arbitrary stored Redis instructions.
        if spec.kind == "followup":
            from .followup_source import APPLY
        else:
            from .reminder_source import APPLY
        raw = spec.encode()
        payload = source_payload(spec)
        binding = hashlib.sha256(_canonical([effect_id, raw, payload]).encode()).hexdigest()
        try:
            result = self.redis.eval(
                PREFIX + APPLY, 5, f"mako:delivery:v1:effect-source:{effect_id}",
                f"mako:delivery:v1:{spec.action_id}", *keys,
                binding, effect_id, spec.action_id, raw, payload, spec.kind + "_complete",
                datetime.now().isoformat(), spec.digest,
            )
            result = result.decode("utf-8") if isinstance(result, bytes) else result
        except (RedisConnectionError, RedisTimeoutError, ConnectionError, TimeoutError) as exc:
            raise EffectUnavailable("source effect outcome unavailable") from exc
        except Exception as exc:
            raise EffectNeedsReview("source effect execution requires review") from exc
        if result == "conflict":
            raise EffectConflict("source effect is bound to different content")
        if result == "incomplete":
            raise EffectIncomplete("previous source mutation may be partial")
        if not isinstance(result, str) or result not in {
            "applied", "already_applied", "superseded", "cancelled",
            "missing", "inconsistent", "wrong_action",
        }:
            raise EffectNeedsReview("invalid source effect response")
        return result
