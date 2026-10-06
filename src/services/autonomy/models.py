from __future__ import annotations

from dataclasses import dataclass
from typing import List, Literal, Optional

Action = Literal["speak", "ask_owner", "silent"]
TargetType = Literal["group", "private", "none"]
Risk = Literal["low", "medium", "high"]


@dataclass
class AutonomyDecision:
    action: Action
    target_type: TargetType
    target_id: Optional[int]
    confidence: float
    risk: Risk
    message: str
    reason: str
    intent: str = "other"

@dataclass
class PendingAction:
    pending_id: str
    target_type: TargetType
    target_id: int
    message: str
    reason: str
    created_at: float
    intent: str = "other"

@dataclass
class TargetHint:
    target_type: TargetType
    target_id: Optional[int]
    ambiguous: bool
    reason: str

@dataclass
class WhitelistCommand:
    action: Literal["add", "remove", "list"]
    target_type: Literal["group", "private"]
    target_ids: List[int]
