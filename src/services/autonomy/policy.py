from __future__ import annotations

from dataclasses import asdict
from typing import List, Literal, Optional

from .models import AutonomyDecision, TargetHint, TargetType


class AutonomyPolicy:
    """Target and decision rules; no driver, matcher or scheduler access."""

    def __init__(self, settings, repository, *, logger):
        self.settings = settings
        self.repository = repository
        self.logger = logger

    def group_ids(self) -> List[int]:
        return sorted(set(self.settings.parse_int_list(self.settings.autonomy_group_ids)) | self.repository.dynamic_allowlist("group"))

    def private_user_ids(self) -> List[int]:
        return sorted(set(self.settings.parse_int_list(self.settings.autonomy_private_user_ids)) | self.repository.dynamic_allowlist("private"))

    def is_enabled(self) -> bool:
        if not self.settings.autonomy_enabled:
            return False
        if self.settings.autonomy_owner_id is None:
            self.logger.error("AUTONOMY_ENABLED=true but AUTONOMY_OWNER_ID is not configured; autonomy is disabled.")
            return False
        return True

    def apply_target_hint(self, decision: AutonomyDecision, hint: TargetHint) -> AutonomyDecision:
        if hint.ambiguous:
            return AutonomyDecision(
                action="ask_owner",
                target_type="none",
                target_id=None,
                confidence=min(decision.confidence, 0.7),
                risk="medium",
                message=decision.message,
                reason=f"{hint.reason}，茉子需要先问清楚目标。",
                intent=decision.intent,
            )
        if hint.target_id is None or hint.target_type == "none":
            return decision
        if decision.target_type != hint.target_type or decision.target_id != hint.target_id:
            self.repository.append_log(
                "target_hint_override",
                {"from": asdict(decision), "hint": asdict(hint)},
            )
        decision.target_type = hint.target_type
        decision.target_id = hint.target_id
        if not self.target_allowed(hint.target_type, hint.target_id):
            decision.action = "ask_owner"
            decision.risk = "medium"
            decision.confidence = min(decision.confidence, 0.75)
            decision.reason = f"{hint.reason}，但目标不在自主行动白名单内。"
        return decision

    def format_whitelist(self, target_type: Literal["group", "private"]) -> str:
        ids = self.group_ids() if target_type == "group" else self.private_user_ids()
        label = "群聊" if target_type == "group" else "私聊好友"
        if not ids:
            return f"茉子现在还没有配置{label}白名单哦。"
        return f"茉子现在的{label}白名单：{', '.join(str(item) for item in ids)}"

    def format_records(self, records) -> str:
        rows: List[str] = []
        allowed_groups = set(self.group_ids())
        allowed_private_users = set(self.private_user_ids())
        for record in records[-self.settings.autonomy_context_limit :]:
            if record.group_id is not None:
                if record.group_id not in allowed_groups:
                    continue
                scene = f"群{record.group_id}"
            else:
                if record.user_id not in allowed_private_users and record.user_id != self.settings.autonomy_owner_id:
                    continue
                scene = f"私聊{record.user_id or 'unknown'}"
            nickname = record.nickname or str(record.user_id or "茉子")
            rows.append(f"[{record.time.strftime('%m-%d %H:%M')}][{scene}][{record.role}][{nickname}] {record.content}")
        return "\n".join(rows) if rows else "暂无可用上下文。"

    def target_allowed(self, target_type: TargetType, target_id: Optional[int]) -> bool:
        if not target_id:
            return False
        if target_type == "group":
            return target_id in self.group_ids()
        if target_type == "private":
            return target_id in self.private_user_ids()
        return False

    def should_ask_owner(self, decision: AutonomyDecision) -> bool:
        if decision.action == "ask_owner":
            return True
        if decision.risk == "medium":
            return True
        return 0.45 <= decision.confidence < 0.82

    def should_act_directly(self, decision: AutonomyDecision) -> bool:
        return (
            decision.action == "speak"
            and decision.confidence >= 0.82
            and decision.risk == "low"
            and bool(decision.message)
        )
