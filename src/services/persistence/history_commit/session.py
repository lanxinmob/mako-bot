"""Replace a session only against its frozen baseline, never newer history."""
import base64
import hashlib
import json

from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from ..effects import EffectConflict, EffectNeedsReview, EffectUnavailable
from ..generation.models import valid_id
from .session_scripts import APPLY
from .snapshot import HistorySnapshot, decode_history, session_key


class HistoryConflict(EffectNeedsReview):
    """Newer session evidence prevents this frozen replacement permanently."""


class SessionHistoryWriter:
    def __init__(self, redis_client):
        self.redis = redis_client

    @staticmethod
    def receipt_key(effect_id: str) -> str:
        if not valid_id(effect_id):
            raise ValueError("invalid session history effect identity")
        return "mako:chat:history:v1:effect:" + effect_id

    def apply(self, effect_id: str, snapshot: HistorySnapshot, messages: list[dict],
              *, max_history_turns: int) -> str:
        """Freeze retention and content at plan creation; retries use the same values."""
        if not isinstance(snapshot, HistorySnapshot):
            raise ValueError("history requires a durable baseline")
        if type(max_history_turns) is not int or not 1 <= max_history_turns <= 2**31 - 1:
            raise ValueError("invalid session history retention")
        if not isinstance(messages, list) or any(not isinstance(item, dict) for item in messages):
            raise ValueError("invalid session history messages")
        receipt = self.receipt_key(effect_id)
        target = session_key(snapshot.session_id)
        if len({receipt, target, snapshot.session_id}) != 3:
            raise ValueError("overlapping history evidence keys")
        replacement = json.dumps(messages[-max_history_turns * 2:], ensure_ascii=False,
                                 allow_nan=False).encode("utf-8")
        decode_history(replacement)
        payload = ["session-history-v1", snapshot.session_id, snapshot.source,
                   None if snapshot.raw is None else base64.b64encode(snapshot.raw).decode("ascii"),
                   base64.b64encode(replacement).decode("ascii"), max_history_turns]
        digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode("utf-8")).hexdigest()
        if self.redis is None:
            raise EffectUnavailable("session history commit requires Redis")
        try:
            result = self.redis.eval(APPLY, 3, receipt, target, snapshot.session_id,
                                     digest, snapshot.source, snapshot.raw or b"", replacement)
            result = result.decode("utf-8") if isinstance(result, bytes) else result
        except (RedisConnectionError, RedisTimeoutError, ConnectionError, TimeoutError) as exc:
            raise EffectUnavailable("session history outcome unavailable") from exc
        except Exception as exc:
            raise EffectNeedsReview("session history commit requires review") from exc
        if result == "history_conflict":
            raise HistoryConflict("newer history preserved; old commit requires review")
        if result == "identity_conflict":
            raise EffectConflict("session history identity is bound to different evidence")
        if result not in {"applied", "already_applied"}:
            raise EffectNeedsReview("invalid session history result")
        return result
