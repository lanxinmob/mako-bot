"""Redis-only authorization and immutable completion for model attempts."""
import json
import secrets

from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from ..effects import EffectConflict, EffectNeedsReview, EffectUnavailable
from .models import GenerationSpec, nonnegative, valid_id
from .scripts import TRANSITION
from .index_scripts import COST_DUE_KEY


class GenerationStore:
    def __init__(self, redis_client):
        self.redis = redis_client

    @staticmethod
    def key(attempt_id):
        if not valid_id(attempt_id):
            raise ValueError("invalid generation attempt id")
        return "mako:generation:v1:" + attempt_id

    def _transition(self, operation, spec, token, amount=""):
        if not isinstance(spec, GenerationSpec) or not valid_id(token):
            raise ValueError("invalid generation authorization")
        if self.redis is None:
            raise EffectUnavailable("generation requires Redis")
        try:
            result = self.redis.eval(TRANSITION, 2, self.key(spec.attempt_id), COST_DUE_KEY,
                                     operation, spec.encode(), token, amount, spec.attempt_id)
            result = result.decode() if isinstance(result, bytes) else result
        except (RedisConnectionError, RedisTimeoutError, ConnectionError, TimeoutError) as exc:
            raise EffectUnavailable("generation state outcome unavailable") from exc
        except Exception as exc:
            raise EffectNeedsReview("generation state requires review") from exc
        if result == "index_unconfirmed":
            raise EffectUnavailable("generation saved; cost index update unconfirmed")
        if result == "conflict":
            raise EffectConflict("generation identity or result conflict")
        allowed = {"start": {"started", "exists"},
                   "complete": {"completed", "missing"},
                   "unknown": {"unknown", "completed", "missing"}}
        if not isinstance(result, str) or result not in allowed[operation]:
            raise EffectNeedsReview("invalid generation state response")
        return result

    def start(self, spec):
        """Only a confirmed first creation grants this caller an invocation token."""
        token = secrets.token_hex(32)
        result = self._transition("start", spec, token)
        return token if result == "started" else None

    def complete(self, spec, token, amount):
        """Freeze estimated cost, including for an answer that will not be sent."""
        amount = float(nonnegative(amount))
        return self._transition("complete", spec, token, json.dumps(amount, allow_nan=False))

    def mark_unknown(self, spec, token):
        return self._transition("unknown", spec, token)
