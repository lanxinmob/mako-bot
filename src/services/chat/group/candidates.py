"""Claim, refresh, cancel and acknowledge disposable chat candidates."""
from __future__ import annotations

from dataclasses import replace

from .models import ChatCandidate, ParticipationDecision
from .policy import ParticipationPolicy
from .window import GroupWindow


class CandidateLifecycle:
    """Single disposable slot per group; owners are revision/generation tokens."""

    def __init__(self, window: GroupWindow, policy: ParticipationPolicy, *,
                 candidate_ttl_seconds: float, lease_seconds: float) -> None:
        self.window = window
        self.policy = policy
        self.candidate_ttl_seconds = candidate_ttl_seconds
        self.lease_seconds = lease_seconds

    def begin_candidate(self, decision: ParticipationDecision) -> ChatCandidate | None:
        """Claim the single chat slot. Tools/reminders are deliberately rejected."""
        if not decision.disposable or decision.action != "reply":
            return None
        if not self.window.decision_is_current(decision):
            return None
        state = self.window.groups[decision.group_id]
        if self.window.trigger(state).kind != "chat" or state.candidate is not None:
            return None
        event = self.window.trigger(state)
        if self.policy.gate(event, state) not in {"direct_call", "followup", "ambient"}:
            return None
        candidate = ChatCandidate(
            decision.group_id, decision.revision, decision.generation,
            event.message_id, event.user_id,
            min(self.window.clock() + self.candidate_ttl_seconds, state.pending_until)
            if state.pending_target is not None else self.window.clock() + self.candidate_ttl_seconds,
            event,
        )
        state.candidate = candidate
        state.batch_started_at = None
        return candidate

    def revalidate_candidate(self, candidate: ChatCandidate,
                             decision: ParticipationDecision) -> ChatCandidate | None:
        """Refresh a sticky direct candidate after reviewing changed context.

        The caller decides against a fresh snapshot, optionally with its semantic
        classifier. A current reply decision must still address the original
        trigger. Never extend its original deadline or resurrect a replaced slot.
        """
        state = self.window.get(candidate.group_id)
        if (state is None or state.candidate != candidate
                or self.window.clock() >= candidate.expires_at
                or not decision.disposable or decision.action != "reply"
                or decision.group_id != candidate.group_id
                or decision.target_message_id != candidate.target_message_id
                or not self.window.decision_is_current(decision)):
            return None
        refreshed = replace(candidate, revision=decision.revision,
                            generation=decision.generation)
        state.candidate = refreshed
        return refreshed

    def candidate_is_current(self, candidate: ChatCandidate) -> bool:
        state = self.window.get(candidate.group_id)
        return bool(state and state.candidate == candidate
                    and state.revision == candidate.revision
                    and state.generation == candidate.generation
                    and self.window.clock() < candidate.expires_at)

    def cancel_candidate(self, candidate: ChatCandidate) -> bool:
        """Cancel only this owner; a stale worker cannot cancel its successor."""
        state = self.window.get(candidate.group_id)
        if state is None or state.candidate != candidate:
            return False
        self.window.advance(state)
        state.batch_started_at = None
        return True

    def mark_sent(self, candidate: ChatCandidate) -> bool:
        """A successful ordinary-chat delivery opens a short same-user lease."""
        state = self.window.get(candidate.group_id)
        # A self echo can precede the API acknowledgement and change revision.
        # Human activity changes generation; never renew ownership after that.
        if (state is None or state.candidate != candidate
                or state.generation != candidate.generation
                or self.window.clock() >= candidate.expires_at):
            return False
        state.sent_message_id = candidate.target_message_id
        state.pending_target = None
        state.pending_until = 0.0
        state.lease_user_id = candidate.user_id
        state.lease_until = self.window.clock() + self.lease_seconds
        self.window.advance(state)
        return True
