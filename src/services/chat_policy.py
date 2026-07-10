"""Pure policies shared by the chat transport and service layers.

The functions in this module deliberately know nothing about NoneBot.  They are
the small, deterministic pieces of the chat request pipeline and can therefore
be tested without starting a bot or connecting to Redis.
"""

from __future__ import annotations

from dataclasses import dataclass
from random import random
from typing import Optional


@dataclass(frozen=True)
class ChatAddress:
    """The protocol-neutral identity of one incoming chat message."""

    message_type: str
    user_id: int
    group_id: Optional[int] = None

    @property
    def session_id(self) -> str:
        if self.message_type == "group" and self.group_id is not None:
            return f"group_{self.group_id}"
        if self.message_type == "private":
            return f"private_{self.user_id}"
        return f"user_{self.user_id}"


def should_reply(
    text: str,
    *,
    is_to_me: bool,
    random_chance: float,
    sample: Optional[float] = None,
) -> bool:
    """Apply the group-chat admission policy.

    Explicit mentions and name mentions always pass.  Other messages are
    admitted according to the configured probability.  ``sample`` is exposed
    for deterministic tests.
    """

    lowered = text.lower()
    if is_to_me or "茉子" in text or "mako" in lowered:
        return True
    chance = min(1.0, max(0.0, random_chance))
    return (random() if sample is None else sample) < chance


def compact_text(value: object, max_chars: int = 160) -> str:
    compact = " ".join(str(value or "").split())
    if len(compact) <= max_chars:
        return compact
    return compact[:max_chars].rstrip() + "..."

