"""Redis-only idempotent writers; callers freeze IDs, timestamps and payloads."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math
import re

from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from src.models.schemas import ChatRecord, OutboundMessageRecord
from .scripts import APPLY


class EffectUnavailable(RuntimeError):
    """Outcome unconfirmed; safe retry requires the identical ID and payload."""


class EffectConflict(ValueError):
    """An effect ID is already bound to different content or a different target."""


class EffectNeedsReview(RuntimeError):
    """Bad data or an unclassified execution error; never retry automatically."""


class EffectIncomplete(EffectNeedsReview):
    """A durable started receipt exists without proof of full target commit."""


class EffectWriter:
    def __init__(self, redis_client):
        self.redis = redis_client

    def _apply(self, effect_id, kind, targets, data):
        if not isinstance(effect_id, str) or not re.fullmatch(r"[0-9a-f]{64}", effect_id):
            raise ValueError("invalid effect identity")
        if self.redis is None:
            raise EffectUnavailable("effects require Redis")
        raw = json.dumps(data, ensure_ascii=False, sort_keys=True, allow_nan=False)
        identity = json.dumps([kind, targets, raw], ensure_ascii=False).encode("utf-8")
        digest = hashlib.sha256(identity).hexdigest()
        key = f"mako:delivery:v1:effect:{effect_id}"
        try:
            result = self.redis.eval(APPLY, len(targets) + 1, key, *targets, digest, kind, raw)
            result = result.decode("utf-8") if isinstance(result, bytes) else result
        except (RedisConnectionError, RedisTimeoutError, ConnectionError, TimeoutError) as exc:
            raise EffectUnavailable("effect outcome unavailable") from exc
        except Exception as exc:
            # Redis scripts do not roll back commands preceding a runtime error.
            # A missing receipt cannot establish that the target was untouched.
            raise EffectNeedsReview("effect execution requires review") from exc
        if result == "conflict":
            raise EffectConflict("effect identity is bound to a different operation")
        if result == "incomplete":
            raise EffectIncomplete("previous target mutation may be partial")
        if not isinstance(result, str) or result not in {"applied", "already_applied"}:
            raise EffectNeedsReview("invalid effect response")
        return result

    @staticmethod
    def _count(value, minimum):
        if type(value) is not int or not minimum <= value <= 2**31 - 1:
            raise ValueError("invalid effect retention")
        return value

    def append_global_record(self, effect_id, record: ChatRecord, *, max_records):
        return self._apply(effect_id, "history", ["all_memory"], {
            "record": record.model_dump_json(exclude={"image_urls"} if not record.image_urls else None),
            "max_records": self._count(max_records, 1000), "ttl": 0})

    def record_outbound(self, effect_id, record: OutboundMessageRecord, *, max_records, ttl):
        return self._apply(effect_id, "outbound", [f"outbound:ledger:{record.target_type}:{record.target_id}"], {
            "record": record.model_dump_json(), "max_records": self._count(max_records, 20),
            "ttl": self._count(ttl, 86400)})

    def consume_cost(self, effect_id, user_id, amount, *, at: datetime):
        if type(user_id) is not int or user_id < 0:
            raise ValueError("invalid effect user")
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount) or amount <= 0:
            raise ValueError("invalid effect cost")
        day = at.strftime("%Y%m%d")
        return self._apply(effect_id, "cost", [f"cost:global:{day}", f"cost:user:{user_id}:{day}"],
                           {"amount": amount, "ttl": 172800})

    def record_news(self, effect_id, fingerprints, *, sent_at: datetime):
        values = list(fingerprints)
        if any(not isinstance(value, str) or not value for value in values):
            raise ValueError("invalid news fingerprint")
        values = sorted(set(values))
        timestamp = sent_at.timestamp()
        if not math.isfinite(timestamp) or timestamp < 0:
            raise ValueError("invalid news timestamp")
        return self._apply(effect_id, "news", ["news:sent"], {"fingerprints": values, "sent_at": timestamp})
