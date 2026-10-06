"""Group participation rules, bounded waits, and optional classification."""
from __future__ import annotations

import asyncio
import re
from typing import Mapping

from .models import Action, Classifier, GroupEvent, GroupSnapshot, GroupState, ParticipationDecision
from .window import GroupWindow


class ParticipationPolicy:
    """Rules and optional classifier over the explicitly supplied window."""

    def __init__(self, window: GroupWindow, *, bot_user_id: str,
                 bot_names: tuple[str, ...], known_bot_ids: set[str],
                 debounce_seconds: float, max_wait_seconds: float,
                 classifier: Classifier | None,
                 classifier_timeout_seconds: float) -> None:
        self.window = window
        self.bot_user_id = bot_user_id
        self.bot_names = bot_names
        self.known_bot_ids = known_bot_ids
        self.debounce_seconds = debounce_seconds
        self.max_wait_seconds = max_wait_seconds
        self.classifier = classifier
        self.classifier_timeout_seconds = classifier_timeout_seconds

    def closure(self, text: str) -> bool:
        compact = re.sub(r"[\s，。！？,.!?~～]+", "", text).casefold()
        for name in self.bot_names:
            if compact.startswith(name):
                compact = compact[len(name):]
            elif compact.endswith(name):
                compact = compact[:-len(name)]
        return compact in {
            "谢谢", "谢谢你", "谢了", "多谢", "好的", "好", "嗯", "嗯嗯", "哦",
            "ok", "okay", "thanks", "thankyou", "懂了", "明白了", "知道了",
            "没事了", "不用了", "算了", "不用回复", "不用回了", "再见", "晚安",
            "解决了谢谢", "已经解决了谢谢", "解决了", "已解决", "搞定了谢谢",
            "谢谢不用了", "不用了谢谢", "好了谢谢", "明白了谢谢",
        }

    def reply_to_other(self, event: GroupEvent, state: GroupState) -> bool:
        if event.reply_to_user_id is not None:
            return event.reply_to_user_id != self.bot_user_id
        if event.reply_to_message_id is not None:
            target = next((item for _, item in state.events
                           if item.message_id == event.reply_to_message_id), None)
            # Unknown quotes are not evidence of a conversation with this bot.
            return target is None or target.user_id != self.bot_user_id
        return bool(event.mentions and self.bot_user_id not in event.mentions)

    def _name_call(self, text: str) -> bool:
        lowered = text.strip().casefold()
        for name in self.bot_names:
            if not lowered.startswith(name):
                continue
            tail = lowered[len(name):]
            if not tail or tail.strip(" ,，:：!！?？~～") == "":
                return True
            # A vocative boundary or second-person request, never arbitrary
            # containment such as '我觉得茉子不错' or 'mako今天说过...'.
            if re.match(r"^[\s,，:：]+", tail):
                return True
            if tail.startswith(("你", "请", "帮我", "能不能", "在吗", "怎么看")):
                return True
        return False

    def gate(self, event: GroupEvent, state: GroupState) -> str:
        if event.kind != "chat":
            return "explicit_workflow"
        if event.is_bot or event.user_id in self.known_bot_ids:
            return "known_bot"
        if self.closure(event.text):
            return "closure"
        # Explicit @ can redirect a quoted message to us for comment.
        if event.direct_call or self.bot_user_id in event.mentions:
            return "direct_call"
        if self.reply_to_other(event, state):
            return "reply_to_other"
        if event.reply_to_user_id == self.bot_user_id:
            return "direct_call"
        if event.reply_to_message_id is not None or self._name_call(event.text):
            return "direct_call"
        if any(name in event.text.casefold() for name in self.bot_names):
            return "name_mention"
        if state.lease_user_id == event.user_id and state.lease_until > self.window.clock():
            return "followup"
        if not event.text.strip():
            return "empty"
        return "ambient"

    @staticmethod
    def _decision(snapshot: GroupSnapshot, action: Action, reason: str,
                  *, wait_seconds: float = 0.0, disposable: bool = True) -> ParticipationDecision:
        return ParticipationDecision(
            action, reason, snapshot.group_id, snapshot.revision, snapshot.generation,
            snapshot.trigger.message_id if snapshot.trigger else None,
            wait_seconds, disposable,
        )

    def _schedule(self, snapshot: GroupSnapshot, reason: str) -> ParticipationDecision:
        state = self.window.groups[snapshot.group_id]
        now = self.window.clock()
        if state.batch_started_at is None:
            state.batch_started_at = next(
                received for received, event in state.events
                if event.message_id == snapshot.trigger.message_id
            )
        last_received = next(received for received, event in reversed(state.events)
                             if not event.outbound)
        deadline = min(last_received + self.debounce_seconds,
                       state.batch_started_at + self.max_wait_seconds)
        remaining = max(0.0, deadline - now)
        return self._decision(snapshot, "wait" if remaining else "reply", reason,
                              wait_seconds=remaining)

    def select_decision(self, snapshot: GroupSnapshot) -> ParticipationDecision:
        """Cheap synchronous selection. Ambient chat defaults to actual silence."""
        if not self.window.current_snapshot(snapshot):
            return self._decision(snapshot, "ignore", "stale_snapshot")
        state = self.window.groups[snapshot.group_id]
        event = snapshot.trigger
        if event is None:
            return self._decision(snapshot, "ignore", "no_inbound")
        reason = self.gate(event, state)
        if reason == "explicit_workflow":
            return self._decision(snapshot, "reply", reason, disposable=False)
        if state.sent_message_id == event.message_id:
            return self._decision(snapshot, "ignore", "already_sent")
        if reason in {"direct_call", "followup"}:
            return self._schedule(snapshot, reason)
        return self._decision(snapshot, "ignore", reason)

    async def decide(self, snapshot: GroupSnapshot) -> ParticipationDecision:
        """Optional classifier contract: {action, target_message_id}.

        Eligible ambient, direct and followup events reach the classifier.
        Reply/wait must target snapshot.trigger exactly; failures fall back
        to the cheap decision. Cancellation propagates to the caller. A model
        asking to wait at the batch deadline becomes ignore, not a forced reply.
        """
        fallback = self.select_decision(snapshot)
        if self.classifier is None or fallback.reason not in {"ambient", "direct_call", "followup"}:
            return fallback
        try:
            result = await asyncio.wait_for(self.classifier(snapshot),
                                          timeout=self.classifier_timeout_seconds)
        except Exception:
            result = None
        if not self.window.current_snapshot(snapshot):
            return self._decision(snapshot, "ignore", "stale_classifier")
        if not isinstance(result, Mapping):
            return fallback
        action = result.get("action")
        if not isinstance(action, str) or action not in {"ignore", "wait", "reply"}:
            return fallback
        if action == "ignore":
            state = self.window.groups[snapshot.group_id]
            state.pending_target = None
            state.pending_until = 0.0
            state.batch_started_at = None
            self.window.advance(state)
            return self._decision(snapshot, "ignore", "model_ignore")
        target = result.get("target_message_id")
        if not isinstance(target, (str, int)) or isinstance(target, bool):
            return fallback
        if str(target) != fallback.target_message_id:
            return fallback
        decision = self._schedule(snapshot, "model_" + action)
        if action == "wait" and decision.action == "reply":
            return self._decision(snapshot, "ignore", "wait_expired")
        return decision
