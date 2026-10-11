"""Anonymous process-local request states; no raw IDs or message content."""
from collections import OrderedDict
from datetime import datetime, timezone
import hashlib
import hmac
import secrets
import time

REASONS = {
    "ambient": "消息未指向茉子", "name_mention": "只是在谈到茉子",
    "reply_to_other": "消息是在回复别人", "closure": "对话已结束或不需要回应",
    "known_bot": "机器人消息", "empty": "没有可回应的内容", "no_inbound": "没有入站消息",
    "direct_call": "明确呼叫茉子", "followup": "同一人的有效续接",
    "stale_snapshot": "上下文快照已失效", "already_sent": "这条请求已得到发送确认",
    "candidate_expired": "回复候选已过期", "answered": "问题已由他人引用回答",
    "replaced": "新的呼叫替代了原请求", "context_changed": "生成期间上下文发生变化",
    "guard_rejected": "发送前候选检查未通过", "access_rejected": "访问规则未接纳",
    "rhythm_blocked": "快速往返正在冷却", "provider_unconfigured": "模型尚未配置",
    "budget_rejected": "预算未接纳", "generation_failed": "生成未完成",
    "task_canceled": "请求任务被取消", "history_unconfirmed": "持久化记录尚未确认",
}
STAGES = {"observed", "waiting", "candidate", "generating", "canceled", "finished"}
SEND_STATES = {"not_started", "in_flight", "confirmed", "unknown", "failed"}


class RhythmTraceStore:
    def __init__(self, *, clock=None, capacity=200, retention_seconds=1800):
        self.clock = clock or time.monotonic
        self.capacity, self.retention_seconds = capacity, retention_seconds
        self.rows = OrderedDict()
        self.salt = secrets.token_bytes(32)
        self.process_started_at = self.stamp()

    @staticmethod
    def stamp():
        return datetime.now(timezone.utc).isoformat()

    def alias(self, *parts):
        value = "\0".join(str(p) for p in parts).encode()
        return hmac.new(self.salt, value, hashlib.sha256).hexdigest()[:24]

    def cleanup(self):
        while self.rows:
            key, (started, _) = next(iter(self.rows.items()))
            if self.clock() - started < self.retention_seconds:
                break
            self.rows.pop(key)

    def observe(self, bot, group, message):
        self.cleanup()
        key = self.alias(bot, group, message)
        if key not in self.rows:
            if len(self.rows) >= self.capacity:
                self.rows.popitem(last=False)
            stamp = self.stamp()
            self.rows[key] = (self.clock(), dict(trace_id=key,
                group_alias="g-" + self.alias(bot, group)[:12], target_alias="m-" + key[:12],
                observed_at=stamp, updated_at=stamp, action=None, reason_code=None,
                reason_label=None, wait_ms=None, stage="observed", send_state="not_started",
                outcome_reason_code=None, outcome_reason_label=None, late_cancel=False))

    def update(self, bot, group, message, *, preserve_canceled=False, **changes):
        self.cleanup()
        entry = self.rows.get(self.alias(bot, group, message))
        if entry is None:
            return  # Delayed updates cannot recreate expired or evicted observations.
        row = entry[1]
        allowed = {"action", "reason_code", "wait_ms", "stage", "send_state", "outcome_reason_code"}
        for key in changes:
            if key not in allowed:
                raise ValueError("unsupported trace field")
        if changes.get("stage") not in STAGES | {None} or changes.get("send_state") not in SEND_STATES | {None}:
            raise ValueError("unsupported trace state")
        if changes.get("action") not in {"ignore", "wait", "reply", None}:
            raise ValueError("unsupported action")
        if changes.get("stage") == "canceled" and row["send_state"] in {"in_flight", "unknown", "confirmed"}:
            row["late_cancel"] = True
            if row["send_state"] == "in_flight":
                row["send_state"] = "unknown"
        if (changes.get("stage") == "finished" or preserve_canceled) and row["stage"] == "canceled":
            changes.pop("stage")
        if (changes.get("outcome_reason_code") == "guard_rejected" and
                row["outcome_reason_code"] in {"answered", "closure", "replaced", "candidate_expired", "context_changed"}):
            changes.pop("outcome_reason_code")
        row.update(changes)
        for key in ("reason_code", "outcome_reason_code"):
            code = row[key]
            row[key.replace("code", "label")] = REASONS.get(code, "未识别的状态原因") if code else None
        row["updated_at"] = self.stamp()

    def snapshot(self, limit=50):
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("limit must be 1..200")
        self.cleanup()
        return {"ok": True, "data": dict(source="runtime", process_started_at=self.process_started_at,
            retention_seconds=self.retention_seconds, items=[
                dict(entry[1]) for entry in list(self.rows.values())[-limit:][::-1]])}
