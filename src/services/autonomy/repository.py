from __future__ import annotations

import json
from dataclasses import asdict
from typing import List, Literal, Optional

from .models import PendingAction, TargetType

DELETE_PENDING = """
redis.call('DEL', KEYS[1])
if redis.call('GET', KEYS[2]) == ARGV[1] then
    redis.call('DEL', KEYS[2])
end
return 1
"""

CREATE_PENDING = """
local ttl = tonumber(ARGV[3])
if not ttl or ttl <= 0 or ttl % 1 ~= 0 then
    return redis.error_reply('invalid pending ttl')
end
-- Validate the pointer before writing: Lua does not roll back runtime errors.
redis.call('GET', KEYS[2])
if redis.call('EXISTS', KEYS[1]) == 1 or redis.call('EXISTS', KEYS[3]) == 1 then
    return 0
end
redis.call('SET', KEYS[1], ARGV[1], 'EX', ttl)
redis.call('SET', KEYS[2], ARGV[2], 'EX', ttl)
return 1
"""


class PendingConflict(ValueError):
    """An existing pending or execution record must never be overwritten."""


class AutonomyRepository:
    """Keep the original Redis/fallback state with explicit dependencies."""

    def __init__(self, settings, redis_client, storage, *, clock, datetime, logger, redis_provider=None):
        self.settings = settings
        self._redis_client = redis_client
        self._redis_provider = redis_provider
        self.storage = storage
        self.clock = clock
        self.datetime = datetime
        self.logger = logger
        self.pending_memory = {}
        self.cooldown_memory = {}
        self.allowlist_memory = {"group": set(), "private": set()}

    @property
    def redis_client(self):
        if self._redis_provider is not None:
            self._redis_client = self._redis_provider()
        return self._redis_client

    @redis_client.setter
    def redis_client(self, value):
        self._redis_provider = None
        self._redis_client = value

    def ttl_expired(self, created_at: float) -> bool:
        return self.clock() - created_at > self.settings.autonomy_pending_ttl_seconds

    def cooldown_key(self, target_type: TargetType, target_id: int) -> str:
        return f"autonomy:cooldown:{target_type}:{target_id}"

    def pending_key(self, pending_id: str) -> str:
        return f"autonomy:pending:{pending_id}"

    def log_key(self) -> str:
        return "autonomy:logs"

    def allowlist_key(self, target_type: Literal["group", "private"]) -> str:
        return f"autonomy:allowlist:{target_type}"

    def dynamic_allowlist(self, target_type: Literal["group", "private"]) -> set[int]:
        key = self.allowlist_key(target_type)
        if self.redis_client:
            try:
                return {int(item) for item in self.redis_client.smembers(key)}
            except Exception as exc:
                self.logger.warning(f"读取自主行动白名单失败({target_type}): {exc}")
        return set(self.allowlist_memory[target_type])

    def add_dynamic_allowlist(self, target_type: Literal["group", "private"], ids: List[int]) -> None:
        if not ids:
            return
        key = self.allowlist_key(target_type)
        if self.redis_client:
            try:
                self.redis_client.sadd(key, *ids)
            except Exception as exc:
                self.logger.warning(f"写入自主行动白名单失败({target_type}): {exc}")
                self.allowlist_memory[target_type].update(ids)
                return
        else:
            self.allowlist_memory[target_type].update(ids)
        self.append_log("allowlist_add", {"target_type": target_type, "ids": ids})

    def remove_dynamic_allowlist(self, target_type: Literal["group", "private"], ids: List[int]) -> None:
        if not ids:
            return
        key = self.allowlist_key(target_type)
        if self.redis_client:
            try:
                self.redis_client.srem(key, *ids)
            except Exception as exc:
                self.logger.warning(f"移除自主行动白名单失败({target_type}): {exc}")
                self.allowlist_memory[target_type].difference_update(ids)
                return
        else:
            self.allowlist_memory[target_type].difference_update(ids)
        self.append_log("allowlist_remove", {"target_type": target_type, "ids": ids})

    def get_cooldown_until(self, target_type: TargetType, target_id: int) -> float:
        key = self.cooldown_key(target_type, target_id)
        if self.redis_client:
            try:
                value = self.redis_client.get(key)
                return float(value) if value else 0.0
            except Exception as exc:
                self.logger.warning(f"读取自主行动冷却失败: {exc}")
        return self.cooldown_memory.get(key, 0.0)

    def set_cooldown(self, target_type: TargetType, target_id: int) -> None:
        seconds = (
            self.settings.autonomy_dm_cooldown_seconds
            if target_type == "private"
            else self.settings.autonomy_cooldown_seconds
        )
        until = self.clock() + seconds
        key = self.cooldown_key(target_type, target_id)
        if self.redis_client:
            try:
                self.redis_client.set(key, until, ex=seconds)
                return
            except Exception as exc:
                self.logger.warning(f"写入自主行动冷却失败: {exc}")
        self.cooldown_memory[key] = until

    def in_cooldown(self, target_type: TargetType, target_id: int) -> bool:
        return self.get_cooldown_until(target_type, target_id) > self.clock()

    def save_pending(self, pending: PendingAction) -> bool:
        if not pending.pending_id or pending.pending_id == "latest":
            raise ValueError("invalid pending id")
        if pending.pending_id in self.pending_memory:
            raise PendingConflict("pending id already exists")
        if self.redis_client:
            try:
                created = self.redis_client.eval(
                    CREATE_PENDING, 3, self.pending_key(pending.pending_id),
                    "autonomy:pending:latest", f"autonomy:execution:{pending.pending_id}",
                    json.dumps(asdict(pending), ensure_ascii=False),
                    pending.pending_id, self.settings.autonomy_pending_ttl_seconds,
                )
            except Exception as exc:
                self.logger.warning(f"保存自主行动确认项失败: {exc}")
            else:
                if created != 1:
                    raise PendingConflict("pending or execution id already exists")
                return True
        self.pending_memory[pending.pending_id] = pending
        return False

    def load_latest_pending(self) -> Optional[PendingAction]:
        if self.redis_client:
            try:
                pending_id = self.redis_client.get("autonomy:pending:latest")
                if not pending_id:
                    return None
                raw = self.redis_client.get(self.pending_key(pending_id))
                if not raw:
                    return None
                data = json.loads(raw)
                pending = PendingAction(**data)
                return None if self.ttl_expired(pending.created_at) else pending
            except Exception as exc:
                self.logger.warning(f"读取自主行动确认项失败: {exc}")
        for pending in sorted(self.pending_memory.values(), key=lambda item: item.created_at, reverse=True):
            if not self.ttl_expired(pending.created_at):
                return pending
        return None

    def delete_pending(self, pending_id: str) -> None:
        if self.redis_client:
            try:
                self.redis_client.eval(DELETE_PENDING, 2, self.pending_key(pending_id),
                                       "autonomy:pending:latest", pending_id)
                self.pending_memory.pop(pending_id, None)
                return
            except Exception as exc:
                self.logger.warning(f"删除自主行动确认项失败: {exc}")
        self.pending_memory.pop(pending_id, None)

    def append_log(self, event: str, payload: dict) -> None:
        item = {
            "event": event,
            "time": self.datetime.now().isoformat(),
            **payload,
        }
        if self.redis_client:
            try:
                self.redis_client.rpush(self.log_key(), json.dumps(item, ensure_ascii=False))
                self.redis_client.ltrim(self.log_key(), -200, -1)
                return
            except Exception as exc:
                self.logger.warning(f"写入自主行动日志失败: {exc}")
        self.logger.info(f"autonomy log: {item}")

    def append_progress_event(self, event_type: str, summary: str, payload: dict) -> None:
        method = getattr(self.storage, "append_progress_event", None)
        if not callable(method):
            self.logger.warning("StorageService.append_progress_event is not available; autonomy progress event skipped.")
            return
        try:
            method(
                {
                    "type": "AutonomyProgressEvent",
                    "source": "autonomy",
                    "event_type": event_type,
                    "summary": summary,
                    "payload": payload,
                    "created_at": self.datetime.now().isoformat(),
                }
            )
        except Exception as exc:
            self.logger.warning(f"写入自主行动进展事件失败: {exc}")

    def append_thought_trace(self, trace_type: str, summary: str, payload: dict) -> None:
        method = getattr(self.storage, "append_thought_trace", None)
        if not callable(method):
            self.logger.warning("StorageService.append_thought_trace is not available; autonomy thought trace skipped.")
            return
        try:
            method(
                {
                    "type": "ThoughtTrace",
                    "source": "autonomy",
                    "trace_type": trace_type,
                    "summary": summary,
                    "payload": payload,
                    "created_at": self.datetime.now().isoformat(),
                }
            )
        except Exception as exc:
            self.logger.warning(f"写入自主行动思考摘要失败: {exc}")
