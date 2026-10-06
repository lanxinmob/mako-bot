"""Classify provably pre-plan sent actions without inventing replayable effects."""
from __future__ import annotations

import json

from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from src.services.persistence.effects import EffectNeedsReview, EffectUnavailable
from .models import DeliverySpec
from .store import DeliveryStore


_CLASSIFY = """
local raw = redis.call('GET', KEYS[1])
if not raw then return 'missing' end
if raw ~= ARGV[1] then return 'changed' end
-- Delivery evidence is permanent. Do not silently remove an unexpected TTL.
if redis.call('PTTL', KEYS[1]) ~= -1 then return 'needs_review' end
redis.call('SET', KEYS[1], ARGV[2])
return 'legacy_review'
"""
_PLAN_FIELDS = {"effects_version", "effects", "plan_json", "plan_digest", "plan_sha1"}
_NETWORK_ERRORS = (RedisConnectionError, RedisTimeoutError, ConnectionError, TimeoutError)


def classify_legacy_sent(client, action_id):
    """CAS only the review flags; retain all transport and source evidence."""
    key = DeliveryStore.key(action_id)
    if client is None:
        raise EffectUnavailable("legacy classification requires Redis")
    try:
        raw = client.get(key)
        if raw is None:
            return "missing"
        raw = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        if not isinstance(raw, str) or len(raw.encode()) > 524288:
            return "needs_review"
        action = json.loads(raw)
        if not isinstance(action, dict) or type(action.get("schema_version")) is not int:
            return "needs_review"
        if action["schema_version"] != 1 or action.get("state") != "sent":
            return "needs_review"
        # Partial or future plans are not legacy records and must not be migrated.
        if _PLAN_FIELDS.intersection(action):
            return "needs_review"
        spec = DeliverySpec(**json.loads(action["spec_json"]))
        if spec.action_id != action_id or action.get("digest") != spec.digest:
            return "needs_review"
        if action.get("effects_state") == "needs_review":
            return "needs_review"
        if action.get("effects_state") not in {None, "not_started", "pending"}:
            return "needs_review"
        action["effects_state"] = "needs_review"
        action["effects_review_reason"] = "legacy_effects_unverified"
        replacement = json.dumps(action, ensure_ascii=False, separators=(",", ":"))
        result = client.eval(_CLASSIFY, 1, key, raw, replacement)
        result = result.decode("utf-8") if isinstance(result, bytes) else result
        if result not in {"missing", "changed", "needs_review", "legacy_review"}:
            raise EffectNeedsReview("invalid legacy classification response")
        return result
    except _NETWORK_ERRORS as exc:
        raise EffectUnavailable("legacy classification outcome unavailable") from exc
    except (ValueError, TypeError, KeyError):
        return "needs_review"
    except Exception as exc:
        raise EffectNeedsReview("legacy classification requires review") from exc
