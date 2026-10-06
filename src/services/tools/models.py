"""Shared tool results and ordered aggregation."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from nonebot.adapters.onebot.v11 import MessageSegment


@dataclass
class ToolExecutionResult:
    fact_lines: List[str] = field(default_factory=list)
    diagnostic_lines: List[str] = field(default_factory=list)
    extra_messages: List[MessageSegment] = field(default_factory=list)
    handled: bool = False

    def merge(self, other: "ToolExecutionResult") -> None:
        self.fact_lines.extend(other.fact_lines)
        self.diagnostic_lines.extend(other.diagnostic_lines)
        self.extra_messages.extend(other.extra_messages)
        self.handled = self.handled or other.handled

    def context_text(self) -> str:
        if self.fact_lines:
            return "\n".join(self.fact_lines).strip()
        if self.diagnostic_lines:
            return "\n".join(self.diagnostic_lines[:2]).strip()
        return ""
