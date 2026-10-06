"""Read exact session evidence without migrating or replacing any history."""
from dataclasses import dataclass
import json

from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from ..effects import EffectNeedsReview, EffectUnavailable


READ = """
for i = 1, 2 do
    local kind = redis.call('TYPE', KEYS[i]).ok
    if kind ~= 'none' then
        if kind ~= 'string' then return redis.error_reply('invalid history type') end
        return {i, redis.call('GET', KEYS[i])}
    end
end
return {0}
"""


def session_key(session_id: str) -> str:
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("invalid history session")
    return "chat:history:" + session_id


def decode_history(raw: bytes) -> list[dict]:
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
        raise ValueError("invalid history sequence")
    return data


@dataclass(frozen=True)
class HistorySnapshot:
    session_id: str
    source: str
    raw: bytes | None

    def __post_init__(self):
        session_key(self.session_id)
        if self.source not in {"current", "legacy", "missing"}:
            raise ValueError("invalid history source")
        if self.source == "missing":
            if self.raw is not None:
                raise ValueError("unexpected missing history data")
        elif not isinstance(self.raw, bytes):
            raise ValueError("history requires exact bytes")
        else:
            decode_history(self.raw)

    def messages(self) -> list[dict]:
        # Each caller gets an independent decoded view; raw remains immutable.
        return [] if self.raw is None else decode_history(self.raw)


class HistorySnapshots:
    def __init__(self, redis_client):
        self.redis = redis_client

    def read(self, session_id: str) -> HistorySnapshot:
        key = session_key(session_id)
        if self.redis is None:
            raise EffectUnavailable("history snapshot requires Redis")
        try:
            result = self.redis.execute_command(
                "EVAL", READ, 2, key, session_id, NEVER_DECODE=True)
            if not isinstance(result, list) or not result or type(result[0]) is not int:
                raise ValueError("invalid history snapshot response")
            source = {0: "missing", 1: "current", 2: "legacy"}[result[0]]
            if len(result) != (1 if source == "missing" else 2):
                raise ValueError("invalid history snapshot arity")
            return HistorySnapshot(session_id, source, None if source == "missing" else result[1])
        except (RedisConnectionError, RedisTimeoutError, ConnectionError, TimeoutError) as exc:
            raise EffectUnavailable("history snapshot unavailable") from exc
        except Exception as exc:
            raise EffectNeedsReview("history snapshot requires review") from exc
