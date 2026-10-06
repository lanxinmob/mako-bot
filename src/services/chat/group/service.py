"""Ephemeral, framework-independent admission for ordinary group chat.

Use one service on one event-loop thread. Observe *every* incoming event before
selecting a decision (including events that other handlers will consume)::

    snapshot = service.observe(GroupEvent(...))
    decision = await service.decide(snapshot)  # or select_decision(snapshot)
    # wait: sleep decision.wait_seconds, check decision_is_current, then decide
    # again using service.snapshot(group_id). Never re-observe to finish a wait.
    candidate = service.begin_candidate(decision)  # reply + disposable only
    # Generate; recheck candidate_is_current after every await and before send.
    # After successful delivery: service.mark_sent(candidate).

Tokens provide cooperative cancellation; this module starts no background tasks
and cannot revoke an already started transport send. Main owns generation tasks,
transport synchronization, access checks, and explicit tool/reminder routing.
Non-disposable decisions must bypass the candidate APIs altogether.
"""

from __future__ import annotations

import math
import time
from dataclasses import replace
from typing import Callable

from .models import ChatCandidate, Classifier, GroupEvent, GroupSnapshot, ParticipationDecision
from .window import GroupWindow
from .policy import ParticipationPolicy
from .candidates import CandidateLifecycle


class GroupConversationService:
    """Explicitly compose observation, admission and candidate lifecycle."""

    def __init__(
        self,
        *,
        bot_user_id: str,
        bot_names: tuple[str, ...] = ("茉子", "mako"),
        known_bot_ids: tuple[str, ...] = (),
        ttl_seconds: float = 600.0,
        max_events: int = 60,
        max_groups: int = 256,
        cleanup_budget: int = 8,
        debounce_seconds: float = 0.8,
        max_wait_seconds: float = 2.5,
        lease_seconds: float = 90.0,
        candidate_ttl_seconds: float = 25.0,
        classifier: Classifier | None = None,
        classifier_timeout_seconds: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        for name, value in {
            "ttl_seconds": ttl_seconds, "lease_seconds": lease_seconds,
            "candidate_ttl_seconds": candidate_ttl_seconds,
            "classifier_timeout_seconds": classifier_timeout_seconds,
        }.items():
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        for value in (debounce_seconds, max_wait_seconds):
            if not math.isfinite(value) or value < 0:
                raise ValueError("wait bounds must be finite and non-negative")
        for value in (max_events, max_groups, cleanup_budget):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError("capacity bounds must be positive integers")
        self.window = GroupWindow(
            ttl_seconds=ttl_seconds, max_events=max_events, max_groups=max_groups,
            cleanup_budget=cleanup_budget, clock=clock,
        )
        self.policy = ParticipationPolicy(
            self.window, bot_user_id=str(bot_user_id),
            bot_names=tuple(name.casefold() for name in bot_names if name),
            known_bot_ids={str(x) for x in known_bot_ids} | {str(bot_user_id)},
            debounce_seconds=debounce_seconds,
            max_wait_seconds=max_wait_seconds, classifier=classifier,
            classifier_timeout_seconds=classifier_timeout_seconds,
        )
        self.candidates = CandidateLifecycle(
            self.window, self.policy, candidate_ttl_seconds=candidate_ttl_seconds,
            lease_seconds=lease_seconds,
        )

    def observe(self, event: GroupEvent) -> GroupSnapshot:
        if event.user_id == self.bot_user_id:
            return self.record_outbound(event)
        state, event, added = self.window.record(event)
        if not added:
            return self.snapshot(event.group_id)
        now = state.touched_at
        if (event.user_id != state.lease_user_id or self.policy.closure(event.text)
                or self.policy.reply_to_other(event, state) or event.kind != "chat"):
            state.lease_user_id = None
            state.lease_until = 0.0
        reason = self.policy.gate(event, state)
        pending = state.pending_target
        resolved = bool(pending and (
            (event.user_id == pending.user_id and self.policy.closure(event.text))
            or event.reply_to_message_id == pending.message_id
        ))
        if resolved:
            state.pending_target = None
            state.pending_until = 0.0
        if reason == "direct_call":
            state.pending_target = event
            state.pending_until = now + self.candidate_ttl_seconds
        keep_candidate = bool(state.candidate and state.pending_target
                              and state.candidate.target_message_id == state.pending_target.message_id)
        self.window.advance(state, keep_candidate=keep_candidate)
        if reason not in {"direct_call", "followup", "ambient"} and state.pending_target is None:
            state.batch_started_at = None
        return self.snapshot(event.group_id)

    def observe_outbound(self, event: GroupEvent, *,
                         lease_user_id: str | None = None) -> GroupSnapshot:
        """Record a successfully sent self event and optionally open a lease.

        Supply reply_to_user_id or lease_user_id for an ordinary chat response.
        Tool/reminder sends never open a chat lease. Call this after delivery;
        if also using mark_sent(candidate), call mark_sent first.
        """
        if event.user_id != self.bot_user_id:
            raise ValueError("outbound event must belong to bot_user_id")
        previous = self.window.get(event.group_id)
        if previous and any(item.message_id == event.message_id
                            for _, item in previous.events):
            return self.snapshot(event.group_id)
        self.observe(replace(event, is_bot=True))
        state = self.window.groups[event.group_id]
        target = lease_user_id if lease_user_id is not None else event.reply_to_user_id
        if event.kind == "chat" and target is not None and str(target) not in self.known_bot_ids:
            state.lease_user_id = str(target)
            state.lease_until = self.clock() + self.lease_seconds
        return self.snapshot(event.group_id)

    def record_outbound(self, event: GroupEvent) -> GroupSnapshot:
        """Add context without claiming, resolving or renewing a conversation."""
        if event.user_id != self.bot_user_id:
            raise ValueError("outbound event must belong to bot_user_id")
        self.window.record(replace(event, is_bot=True, outbound=True))
        return self.snapshot(event.group_id)

    @property
    def classifier(self) -> Classifier | None:
        return self.policy.classifier

    @classifier.setter
    def classifier(self, value: Classifier | None) -> None:
        self.policy.classifier = value

    @property
    def classifier_timeout_seconds(self) -> float:
        return self.policy.classifier_timeout_seconds

    @classifier_timeout_seconds.setter
    def classifier_timeout_seconds(self, value: float) -> None:
        self.policy.classifier_timeout_seconds = value

    @property
    def group_count(self) -> int:
        return self.window.group_count

    def cleanup(self) -> int:
        return self.window.cleanup()

    def snapshot(self, group_id: str) -> GroupSnapshot:
        return self.window.snapshot(group_id)

    def select_decision(self, snapshot: GroupSnapshot) -> ParticipationDecision:
        return self.policy.select_decision(snapshot)

    async def decide(self, snapshot: GroupSnapshot) -> ParticipationDecision:
        return await self.policy.decide(snapshot)

    def decision_is_current(self, decision: ParticipationDecision) -> bool:
        return self.window.decision_is_current(decision)

    def begin_candidate(self, decision: ParticipationDecision) -> ChatCandidate | None:
        return self.candidates.begin_candidate(decision)

    def revalidate_candidate(self, candidate: ChatCandidate,
                             decision: ParticipationDecision) -> ChatCandidate | None:
        return self.candidates.revalidate_candidate(candidate, decision)

    def candidate_is_current(self, candidate: ChatCandidate) -> bool:
        return self.candidates.candidate_is_current(candidate)

    def cancel_candidate(self, candidate: ChatCandidate) -> bool:
        return self.candidates.cancel_candidate(candidate)

    def mark_sent(self, candidate: ChatCandidate) -> bool:
        return self.candidates.mark_sent(candidate)

    @property
    def ttl_seconds(self) -> float:
        return self.window.ttl_seconds

    @ttl_seconds.setter
    def ttl_seconds(self, value: float) -> None:
        self.window.ttl_seconds = value

    @property
    def max_events(self) -> int:
        return self.window.max_events

    @max_events.setter
    def max_events(self, value: int) -> None:
        self.window.max_events = value

    @property
    def max_groups(self) -> int:
        return self.window.max_groups

    @max_groups.setter
    def max_groups(self, value: int) -> None:
        self.window.max_groups = value

    @property
    def cleanup_budget(self) -> int:
        return self.window.cleanup_budget

    @cleanup_budget.setter
    def cleanup_budget(self, value: int) -> None:
        self.window.cleanup_budget = value

    @property
    def clock(self) -> Callable[[], float]:
        return self.window.clock

    @clock.setter
    def clock(self, value: Callable[[], float]) -> None:
        self.window.clock = value

    @property
    def bot_user_id(self) -> str:
        return self.policy.bot_user_id

    @bot_user_id.setter
    def bot_user_id(self, value: str) -> None:
        self.policy.bot_user_id = value

    @property
    def bot_names(self) -> tuple[str, ...]:
        return self.policy.bot_names

    @bot_names.setter
    def bot_names(self, value: tuple[str, ...]) -> None:
        self.policy.bot_names = value

    @property
    def known_bot_ids(self) -> set[str]:
        return self.policy.known_bot_ids

    @known_bot_ids.setter
    def known_bot_ids(self, value: set[str]) -> None:
        self.policy.known_bot_ids = value

    @property
    def debounce_seconds(self) -> float:
        return self.policy.debounce_seconds

    @debounce_seconds.setter
    def debounce_seconds(self, value: float) -> None:
        self.policy.debounce_seconds = value

    @property
    def max_wait_seconds(self) -> float:
        return self.policy.max_wait_seconds

    @max_wait_seconds.setter
    def max_wait_seconds(self, value: float) -> None:
        self.policy.max_wait_seconds = value

    @property
    def lease_seconds(self) -> float:
        return self.candidates.lease_seconds

    @lease_seconds.setter
    def lease_seconds(self, value: float) -> None:
        self.candidates.lease_seconds = value

    @property
    def candidate_ttl_seconds(self) -> float:
        return self.candidates.candidate_ttl_seconds

    @candidate_ttl_seconds.setter
    def candidate_ttl_seconds(self, value: float) -> None:
        self.candidates.candidate_ttl_seconds = value
