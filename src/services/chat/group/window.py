"""Bounded short-term group observation storage."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import replace
from typing import Callable

from .models import GroupEvent, GroupSnapshot, GroupState, ParticipationDecision


class GroupWindow:
    """Own receipt-time LRU, bounded events, and monotonic token counters."""

    def __init__(self, *, ttl_seconds: float, max_events: int, max_groups: int,
                 cleanup_budget: int, clock: Callable[[], float]) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_events = max_events
        self.max_groups = max_groups
        self.cleanup_budget = cleanup_budget
        self.clock = clock
        self.groups: OrderedDict[str, GroupState] = OrderedDict()
        self._revision = 0
        self._generation = 0

    @property
    def group_count(self) -> int:
        return len(self.groups)

    def advance(self, state: GroupState, *, keep_candidate: bool = False) -> None:
        self._generation += 1
        state.generation = self._generation
        if not keep_candidate:
            state.candidate = None

    def cleanup(self) -> int:
        """Drop at most cleanup_budget inactive groups; no full-map scan."""
        now = self.clock()
        removed = 0
        while self.groups and removed < self.cleanup_budget:
            key = next(iter(self.groups))
            if now - self.groups[key].touched_at < self.ttl_seconds:
                break
            del self.groups[key]
            removed += 1
        return removed

    def get(self, group_id: str) -> GroupState | None:
        state = self.groups.get(str(group_id))
        if state is None:
            return None
        now = self.clock()
        if now - state.touched_at >= self.ttl_seconds:
            del self.groups[str(group_id)]
            return None
        while state.events and now - state.events[0][0] >= self.ttl_seconds:
            state.events.popleft()
        if state.lease_until <= now:
            state.lease_user_id = None
            state.lease_until = 0.0
        if state.candidate is not None and state.candidate.expires_at <= now:
            self.advance(state)
            state.batch_started_at = None
        if state.pending_target is not None and (
            state.pending_until <= now or not any(
                event.message_id == state.pending_target.message_id for _, event in state.events
            )
        ):
            state.pending_target = None
            state.pending_until = 0.0
            self.advance(state)
            state.batch_started_at = None
        return state

    def record(self, event: GroupEvent) -> tuple[GroupState, GroupEvent, bool]:
        self.cleanup()
        now = self.clock()
        state = self.get(event.group_id)
        if state is None:
            if len(self.groups) >= self.max_groups:
                self.groups.popitem(last=False)
            state = GroupState(touched_at=now)
            self.groups[event.group_id] = state
        if any(item.message_id == event.message_id for _, item in state.events):
            return state, event, False
        # Bound stored payloads too, not just the number of messages.
        event = replace(event, text=event.text[:2000], nickname=event.nickname[:100])
        state.events.append((now, event))
        while len(state.events) > self.max_events:
            state.events.popleft()
        self._revision += 1
        state.revision = self._revision
        state.touched_at = now
        self.groups.move_to_end(event.group_id)
        return state, event, True

    def snapshot(self, group_id: str) -> GroupSnapshot:
        group_id = str(group_id)
        state = self.get(group_id)
        if state is None:
            return GroupSnapshot(group_id, 0, 0, ())
        return GroupSnapshot(
            group_id, state.revision, state.generation,
            tuple(event for _, event in state.events),
            state.lease_user_id, state.lease_until,
            self.trigger(state),
        )

    @staticmethod
    def trigger(state: GroupState) -> GroupEvent | None:
        latest = next((event for _, event in reversed(state.events)
                       if not event.outbound), None)
        if latest is None:
            return None
        if latest.kind != "chat":
            return latest
        return state.pending_target or latest

    def current_snapshot(self, snapshot: GroupSnapshot) -> bool:
        state = self.get(snapshot.group_id)
        return bool(state and state.revision == snapshot.revision
                    and state.generation == snapshot.generation
                    and tuple(event for _, event in state.events) == snapshot.events
                    and self.trigger(state) == snapshot.trigger)

    def decision_is_current(self, decision: ParticipationDecision) -> bool:
        state = self.get(decision.group_id)
        return bool(state and state.revision == decision.revision
                    and state.generation == decision.generation and state.events
                    and self.trigger(state) is not None
                    and self.trigger(state).message_id == decision.target_message_id
                    and state.sent_message_id != decision.target_message_id)
