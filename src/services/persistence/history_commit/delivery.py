"""A saved plan is not permission to replay either transport or history."""
from dataclasses import dataclass
import json
import secrets

from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from ..effects import EffectNeedsReview, EffectUnavailable
from ..generation.models import valid_id
from .delivery_scripts import CREATE, TRANSITION
from .plans import HistoryDeliveryPlan, MAX_PLAN_BYTES, integer, timestamp_ms


@dataclass(frozen=True)
class HistoryDeliverySnapshot:
    raw: str
    plan: HistoryDeliveryPlan
    state: str
    token: str
    delivered_at_ms: int | None
    confirmation_source: str = "transport"


def decode_delivery(raw: str, action_id: str) -> HistoryDeliverySnapshot:
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_PLAN_BYTES * 2 + 8192:
        raise ValueError("invalid history delivery capacity")
    data = json.loads(raw)
    if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1:
        raise ValueError("invalid history delivery version")
    plan = HistoryDeliveryPlan(data["plan_json"])
    if plan.action_id != action_id or data.get("digest") != plan.digest or not valid_id(data.get("token")):
        raise ValueError("invalid history delivery binding")
    state = data.get("state")
    if state not in {"prepared", "sending", "unknown", "sent", "rejected", "abandoned"}:
        raise ValueError("invalid history delivery state")
    timestamp_ms(data.get("created_at_ms"))
    if state in {"sending", "unknown", "sent", "abandoned"}:
        timestamp_ms(data.get("begun_at_ms"))
    delivered = data.get("delivered_at_ms")
    tasks = data.get("tasks")
    if not isinstance(tasks, dict) or set(tasks) != {"session", "global"}:
        raise ValueError("invalid history delivery tasks")
    source = data.get("confirmation_source", "transport")
    owner_fields = {"owner_id", "owner_conclusion", "reviewed_at_ms"}
    if source == "owner":
        operator = data.get("owner_id")
        if (state not in {"sent", "abandoned"} or data.get("owner_conclusion") != state
                or not isinstance(operator, str) or not operator.isascii() or not operator.isdigit()
                or "delivered_at_ms" not in data or delivered is not None or data.get("task_meta", {}) != {}):
            raise ValueError("invalid manual history confirmation")
        integer(int(operator), 1)
        timestamp_ms(data.get("reviewed_at_ms"))
        allowed = {"needs_review"} if state == "sent" else {"dormant"}
    elif source == "transport" and not owner_fields.intersection(data) and state != "abandoned":
        if state == "sent":
            timestamp_ms(delivered)
        elif delivered is not None:
            raise ValueError("unconfirmed history delivery has a sent time")
        allowed = {"pending", "leased", "retry_wait", "complete", "needs_review"} if state == "sent" else {"dormant"}
    else:
        raise ValueError("invalid history confirmation source")
    if any(task not in allowed for task in tasks.values()):
        raise ValueError("invalid history effect activation")
    return HistoryDeliverySnapshot(raw, plan, state, data["token"], delivered, source)


class HistoryDeliveryStore:
    def __init__(self, redis_client):
        self.redis = redis_client

    @staticmethod
    def key(action_id: str) -> str:
        if not valid_id(action_id):
            raise ValueError("invalid history delivery identity")
        return "mako:chat:delivery:v1:" + action_id

    def _read(self, operation):
        if self.redis is None:
            raise EffectUnavailable("history delivery requires Redis")
        try:
            return operation()
        except (EffectUnavailable, EffectNeedsReview):
            raise
        except (RedisConnectionError, RedisTimeoutError, ConnectionError, TimeoutError) as exc:
            raise EffectUnavailable("history delivery outcome unavailable") from exc
        except Exception as exc:
            raise EffectNeedsReview("history delivery requires review") from exc

    def create(self, plan: HistoryDeliveryPlan) -> str | None:
        if not isinstance(plan, HistoryDeliveryPlan):
            raise ValueError("history delivery requires a frozen plan")
        key, token = self.key(plan.action_id), secrets.token_hex(32)

        def run():
            result = self.redis.eval(CREATE, 1, key, plan.raw, plan.digest, token)
            result = result.decode() if isinstance(result, bytes) else result
            if result not in {"created", "exists"}:
                raise EffectNeedsReview("invalid history plan creation response")
            return token if result == "created" else None

        return self._read(run)

    def inspect(self, action_id: str) -> HistoryDeliverySnapshot | None:
        key = self.key(action_id)

        def run():
            raw = self.redis.get(key)
            if raw is None:
                return None
            raw = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            return decode_delivery(raw, action_id)

        return self._read(run)

    def transition(self, action_id: str, token: str, operation: str,
                   *, delivered_at_ms: int | None = None) -> str:
        """Only the first confirmed begin authorizes the actual transport callback."""
        if operation not in {"begin", "sent", "unknown", "reject"} or not valid_id(token):
            raise ValueError("invalid history delivery transition")
        if operation == "sent":
            timestamp_ms(delivered_at_ms)
        elif delivered_at_ms is not None:
            raise ValueError("unexpected history delivery time")
        snapshot = self.inspect(action_id)
        if snapshot is None:
            return "missing"

        def run():
            result = self.redis.eval(TRANSITION, 1, self.key(action_id), snapshot.raw, operation, token,
                                     delivered_at_ms if delivered_at_ms is not None else "")
            result = result.decode() if isinstance(result, bytes) else result
            if result not in {"prepared", "sending", "sent", "unknown", "rejected", "missing", "changed", "denied"}:
                raise EffectNeedsReview("invalid history delivery transition response")
            return result

        return self._read(run)
