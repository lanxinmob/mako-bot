"""Conversation pacing and loop protection for ordinary chat replies."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Optional

from src.core.config import Settings, get_settings
from src.services.storage import StorageService


@dataclass
class RhythmState:
    last_reply_at: float = 0.0
    last_incoming_at: float = 0.0
    last_sender_id: Optional[int] = None
    rapid_turns: int = 0
    automation_score: float = 0.0
    cooldown_until: float = 0.0
    cooldown_level: int = 0
    last_boundary_reason: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RhythmState":
        return cls(
            last_reply_at=float(payload.get("last_reply_at", 0.0) or 0.0),
            last_incoming_at=float(payload.get("last_incoming_at", 0.0) or 0.0),
            last_sender_id=(
                int(payload["last_sender_id"])
                if payload.get("last_sender_id") is not None
                else None
            ),
            rapid_turns=max(0, int(payload.get("rapid_turns", 0) or 0)),
            automation_score=float(payload.get("automation_score", 0.0) or 0.0),
            cooldown_until=float(payload.get("cooldown_until", 0.0) or 0.0),
            cooldown_level=max(0, int(payload.get("cooldown_level", 0) or 0)),
            last_boundary_reason=str(payload.get("last_boundary_reason", "") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "last_reply_at": self.last_reply_at,
            "last_incoming_at": self.last_incoming_at,
            "last_sender_id": self.last_sender_id,
            "rapid_turns": self.rapid_turns,
            "automation_score": self.automation_score,
            "cooldown_until": self.cooldown_until,
            "cooldown_level": self.cooldown_level,
            "last_boundary_reason": self.last_boundary_reason,
        }


@dataclass(frozen=True)
class RhythmDecision:
    allowed: bool
    force_short: bool = False
    boundary: bool = False
    known_bot: bool = False
    automation_score: float = 0.0
    rapid_turns: int = 0
    social_state: str = "normal"
    reason: str = ""


class ChatRhythmService:
    """Persisted, conservative turn-taking state for group conversations."""

    def __init__(
        self,
        storage: Optional[StorageService] = None,
        *,
        clock=time.time,
        settings: Optional[Settings] = None,
    ) -> None:
        self.storage = storage or StorageService()
        self.settings = settings or get_settings()
        self.clock = clock
        self._memory: dict[str, RhythmState] = {}
        self._known_bot_ids = set(self.settings.parse_int_list(self.settings.known_bot_user_ids))

    @staticmethod
    def _key(session_id: str) -> str:
        return f"chat:rhythm:{session_id}"

    def _load(self, session_id: str) -> RhythmState:
        try:
            redis = self.storage.redis
            if redis:
                raw = redis.get(self._key(session_id))
                if raw:
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8")
                    return RhythmState.from_dict(json.loads(raw))
        except Exception:
            # A transient rhythm-state failure should never prevent ordinary chat.
            pass
        return self._memory.get(session_id, RhythmState())

    def _save(self, session_id: str, state: RhythmState) -> None:
        self._memory[session_id] = state
        try:
            redis = self.storage.redis
            if redis:
                redis.set(self._key(session_id), json.dumps(state.to_dict(), ensure_ascii=False))
                redis.expire(
                    self._key(session_id),
                    max(self.settings.chat_rhythm_max_cooldown_seconds * 2, 1800),
                )
        except Exception:
            pass

    def admit(
        self,
        session_id: str,
        *,
        message_type: str,
        sender_id: int,
        now: Optional[float] = None,
    ) -> RhythmDecision:
        if message_type != "group" or not self.settings.chat_rhythm_enabled:
            return RhythmDecision(True)

        current = self.clock() if now is None else now
        state = self._load(session_id)
        known_bot = sender_id in self._known_bot_ids
        window = max(1, self.settings.chat_rhythm_window_seconds)

        quiet_seconds = current - state.last_reply_at if state.last_reply_at else 0.0
        if state.last_reply_at and quiet_seconds > window * 2:
            state.rapid_turns = 0
            state.automation_score = 0.0
        if state.last_reply_at and quiet_seconds > self.settings.chat_rhythm_max_cooldown_seconds * 2:
            state.cooldown_level = 0

        if state.cooldown_until > current:
            is_human_interruption = (
                sender_id != state.last_sender_id and not known_bot
            )
            if is_human_interruption:
                state.cooldown_until = 0.0
                state.rapid_turns = 0
                state.automation_score = 0.0
                state.last_sender_id = sender_id
                state.last_incoming_at = current
                self._save(session_id, state)
                return RhythmDecision(True, social_state="human_interruption")
            return RhythmDecision(
                False,
                known_bot=known_bot,
                automation_score=state.automation_score,
                rapid_turns=state.rapid_turns,
                social_state="cooldown",
                reason="rapid automated exchange is cooling down",
            )

        same_sender = sender_id == state.last_sender_id
        rapid = (
            same_sender
            and state.last_reply_at > 0
            and current - state.last_reply_at <= self.settings.chat_rhythm_fast_turn_seconds
        )
        next_rapid_turns = state.rapid_turns + 1 if rapid else 0
        threshold = 2 if known_bot else 3
        automation_score = 1.0 if known_bot else min(1.0, next_rapid_turns / threshold)
        boundary = rapid and next_rapid_turns >= threshold

        state.last_incoming_at = current
        state.last_sender_id = sender_id
        state.rapid_turns = next_rapid_turns
        state.automation_score = automation_score
        self._save(session_id, state)
        return RhythmDecision(
            True,
            force_short=rapid,
            boundary=boundary,
            known_bot=known_bot,
            automation_score=automation_score,
            rapid_turns=next_rapid_turns,
            social_state="rapid_exchange" if rapid else "normal",
            reason="rapid exchange" if rapid else "normal turn",
        )

    def mark_sent(
        self,
        session_id: str,
        *,
        sender_id: int,
        boundary: bool = False,
        now: Optional[float] = None,
    ) -> None:
        current = self.clock() if now is None else now
        state = self._load(session_id)
        state.last_reply_at = current
        state.last_sender_id = sender_id
        if boundary:
            level = state.cooldown_level
            duration = min(
                self.settings.chat_rhythm_max_cooldown_seconds,
                self.settings.chat_rhythm_cooldown_seconds * (3**level),
            )
            state.cooldown_until = current + duration
            state.cooldown_level = min(level + 1, 4)
            state.last_boundary_reason = "rapid automated exchange"
        self._save(session_id, state)

    @staticmethod
    def boundary_text() -> str:
        return "这个话题开始原地打转了，茉子先歇会儿。"
