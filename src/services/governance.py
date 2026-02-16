from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from src.core.config import get_settings
from src.services.storage import StorageService


@dataclass
class AccessDecision:
    allowed: bool
    reason: str = ""


class GovernanceService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.storage = StorageService()
        self._admin_ids = set(self.settings.parse_int_list(self.settings.admin_user_ids))
        self._config_blacklist_users = set(self.settings.parse_int_list(self.settings.blacklist_user_ids))
        self._config_blacklist_groups = set(self.settings.parse_int_list(self.settings.blacklist_group_ids))
        self._admin_only_tools = set(self.settings.parse_name_list(self.settings.admin_only_tool_list))
        self._tool_cost_overrides = self.settings.parse_cost_overrides(self.settings.tool_cost_overrides)
        self._group_enable = set(self.settings.parse_name_list(self.settings.group_tool_enable_list))
        self._group_disable = set(self.settings.parse_name_list(self.settings.group_tool_disable_list))
        self._private_enable = set(self.settings.parse_name_list(self.settings.private_tool_enable_list))
        self._private_disable = set(self.settings.parse_name_list(self.settings.private_tool_disable_list))

    def is_admin_user(self, user_id: int, is_group_admin: bool = False) -> bool:
        return user_id in self._admin_ids or is_group_admin

    def can_chat(self, user_id: int, group_id: Optional[int] = None) -> AccessDecision:
        if user_id in self._config_blacklist_users or self.storage.is_user_blacklisted(user_id):
            return AccessDecision(False, "user is blacklisted")
        if group_id and (group_id in self._config_blacklist_groups or self.storage.is_group_blacklisted(group_id)):
            return AccessDecision(False, "group is blacklisted")
        return AccessDecision(True)

    def tool_allowed(
        self,
        tool_name: str,
        *,
        user_id: int,
        message_type: str,
        group_id: Optional[int] = None,
        is_group_admin: bool = False,
    ) -> AccessDecision:
        chat_access = self.can_chat(user_id, group_id)
        if not chat_access.allowed:
            return chat_access

        if message_type == "group":
            if tool_name in self._group_disable:
                return AccessDecision(False, "tool disabled in group scene")
            if self._group_enable and tool_name not in self._group_enable:
                return AccessDecision(False, "tool not enabled in group scene")
        else:
            if tool_name in self._private_disable:
                return AccessDecision(False, "tool disabled in private scene")
            if self._private_enable and tool_name not in self._private_enable:
                return AccessDecision(False, "tool not enabled in private scene")

        if tool_name in self._admin_only_tools and not self.is_admin_user(user_id, is_group_admin):
            return AccessDecision(False, "admin permission required")
        return AccessDecision(True)

    def estimate_tool_cost(self, tool_name: str) -> float:
        if tool_name in self._tool_cost_overrides:
            return self._tool_cost_overrides[tool_name]
        defaults = {
            "image.generate": 0.10,
            "image.describe": 0.02,
            "search.web": 0.02,
            "search.summarize_url": 0.02,
            "language.tts": 0.02,
            "language.stt": 0.02,
        }
        return defaults.get(tool_name, 0.005)

    def estimate_llm_cost(self, input_chars: int, output_chars: int = 0) -> float:
        return (
            input_chars / 1000.0 * self.settings.llm_cost_per_1k_chars_input
            + output_chars / 1000.0 * self.settings.llm_cost_per_1k_chars_output
        )

    def can_consume_cost(self, user_id: int, amount: float, *, now: Optional[datetime] = None) -> AccessDecision:
        if not self.settings.cost_control_enabled:
            return AccessDecision(True)
        now = now or datetime.now()
        global_used = self.storage.get_daily_cost(None, at=now)
        user_used = self.storage.get_daily_cost(user_id, at=now)
        if global_used + amount > self.settings.daily_cost_limit_global:
            return AccessDecision(False, "global daily budget exhausted")
        if user_used + amount > self.settings.daily_cost_limit_user:
            return AccessDecision(False, "user daily budget exhausted")
        return AccessDecision(True)

    def consume_cost(self, user_id: int, amount: float, *, now: Optional[datetime] = None) -> None:
        self.storage.consume_cost(user_id, amount, at=now or datetime.now())
