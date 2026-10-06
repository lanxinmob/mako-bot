"""Immutable public tokens and process-local group state."""
from __future__ import annotations

import json
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Literal, Mapping


Action = Literal["ignore", "wait", "reply"]


@dataclass(frozen=True)
class GroupEvent:
    group_id: str
    message_id: str
    user_id: str
    text: str = ""
    timestamp: float = field(default_factory=time.time)
    nickname: str = ""
    reply_to_message_id: str | None = None
    reply_to_user_id: str | None = None
    mentions: tuple[str, ...] = ()
    message_type: str = "text"
    is_bot: bool = False
    direct_call: bool = False
    kind: Literal["chat", "tool", "reminder"] = "chat"
    outbound: bool = False

    def __post_init__(self) -> None:
        # Protocol adapters commonly supply integer QQ/message identifiers.
        for name in ("group_id", "message_id", "user_id"):
            value = getattr(self, name)
            if value is None or str(value) == "":
                raise ValueError(f"{name} must identify an event")
            object.__setattr__(self, name, str(value))
        for name in ("reply_to_message_id", "reply_to_user_id"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, str(value))
        object.__setattr__(self, "mentions", tuple(str(x) for x in self.mentions)[:32])
        if self.kind not in {"chat", "tool", "reminder"}:
            raise ValueError("kind must be chat, tool, or reminder")


@dataclass(frozen=True)
class GroupSnapshot:
    group_id: str
    revision: int
    generation: int
    events: tuple[GroupEvent, ...]
    lease_user_id: str | None = None
    lease_until: float = 0.0  # monotonic time, unlike event.timestamp
    trigger: GroupEvent | None = None

    def render(self, max_chars: int = 6000) -> str:
        """Recent events as bounded JSON lines (untrusted conversation data).

        Keep the newest lines when the prompt budget is exhausted. Newlines in
        user text are escaped, so text cannot manufacture metadata lines.
        """
        if max_chars < 1:
            return ""
        lines: list[str] = []
        remaining = max_chars
        for event in reversed(self.events):
            line = json.dumps({
                "message_id": event.message_id, "user_id": event.user_id,
                "nickname": event.nickname, "time": event.timestamp,
                "reply_to_message_id": event.reply_to_message_id,
                "reply_to_user_id": event.reply_to_user_id,
                "mentions": event.mentions, "type": event.message_type,
                "kind": event.kind, "is_bot": event.is_bot, "text": event.text,
            }, ensure_ascii=False)
            cost = len(line) + bool(lines)
            if cost > remaining:
                if not lines:
                    # At very small budgets the result is a text excerpt.
                    return line[:max_chars]
                break
            lines.append(line)
            remaining -= cost
        return "\n".join(reversed(lines))


def render_snapshot(snapshot: GroupSnapshot, max_chars: int = 6000) -> str:
    return snapshot.render(max_chars)


@dataclass(frozen=True)
class ParticipationDecision:
    action: Action
    reason: str
    group_id: str
    revision: int
    generation: int
    target_message_id: str | None = None
    wait_seconds: float = 0.0
    disposable: bool = True


@dataclass(frozen=True)
class ChatCandidate:
    group_id: str
    revision: int
    generation: int
    target_message_id: str
    user_id: str
    expires_at: float
    trigger: GroupEvent


Classifier = Callable[[GroupSnapshot], Awaitable[Mapping[str, object]]]


@dataclass
class GroupState:
    events: deque[tuple[float, GroupEvent]] = field(default_factory=deque)
    revision: int = 0
    generation: int = 0
    touched_at: float = 0.0
    batch_started_at: float | None = None
    lease_user_id: str | None = None
    lease_until: float = 0.0
    candidate: ChatCandidate | None = None
    sent_message_id: str | None = None
    pending_target: GroupEvent | None = None
    pending_until: float = 0.0
