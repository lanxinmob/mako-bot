"""Durable reminder transport; scheduler callbacks supply the expected revision."""
from __future__ import annotations

import asyncio
import logging

from nonebot.adapters.onebot.v11 import Message, MessageSegment

from src.services.persistence.reminder_state import REVISION_KEY, ReminderStateStore
from .dispatcher import dispatch
from .effects.producer import production_plan, settle_confirmed
from .observation import observe_group_output, observe_plugin_output
from .state import DeliveryAttempt, DeliverySpec, DeliveryStore, DeliveryUnavailable

logger = logging.getLogger(__name__)


def reminder_spec(snapshot, *, valid_until_ms):
    """Deadline comes from the scheduler's misfire plus outbound wait budget."""
    item = snapshot.record
    return DeliverySpec(
        "reminder", snapshot.intent["bot_id"], "group", str(item.group_id),
        item.reminder_id, snapshot.revision, item.content, valid_until_ms,
        "reminders", item.reminder_id, snapshot.digest, REVISION_KEY,
    )


class ReminderDelivery:
    def __init__(self, redis_client, *, schedule=dispatch, queued_lease_seconds=180):
        self.source = ReminderStateStore(redis_client)
        self.store = DeliveryStore(redis_client, queued_lease_seconds=queued_lease_seconds, require_effects=True)
        self.schedule = schedule

    async def deliver(self, bot, job_id, revision, *, valid_until_ms, recovery_spec=None):
        snapshot = await asyncio.to_thread(self.source.load, job_id)
        if snapshot is None or not revision or snapshot.revision != revision:
            return False
        binding = await asyncio.to_thread(self.source.bind_bot, snapshot, str(bot.self_id))
        if not binding.ok:
            return False
        snapshot = binding.snapshot
        spec = reminder_spec(snapshot, valid_until_ms=valid_until_ms)
        if recovery_spec is not None and spec != recovery_spec:
            return False
        claim_operation = self.store.recover if recovery_spec is not None else self.store.claim
        claim = await asyncio.to_thread(claim_operation, spec, plan=production_plan(spec))
        if not claim.ok:
            return False
        attempt = DeliveryAttempt(self.store, spec, claim.token)

        async def send(frozen):
            # Text must not be parsed as CQ codes supplied in reminder content.
            message = Message(MessageSegment.text(frozen.payload))
            result = await bot.send_group_msg(group_id=int(frozen.target_id), message=message)
            acknowledged = result is True or (
                isinstance(result, dict) and result.get("message_id") is not None)
            if acknowledged:
                observe_plugin_output(bot.self_id, "group", frozen.target_id, result, message, "reminder")
                try:
                    observe_group_output(bot.self_id, int(frozen.target_id), result, message, "reminder")
                except Exception:
                    logger.warning("Reminder delivered; group observation unresolved")
            return acknowledged

        try:
            await self.schedule("group", snapshot.record.group_id,
                                lambda: attempt.send(send), category="reminder")
        finally:
            if not attempt.attempted:
                try:
                    await asyncio.to_thread(self.store.reject_before_send, spec.action_id, claim.token)
                except DeliveryUnavailable:
                    logger.warning("Unsent reminder reservation unresolved; lease may recover it")
        if not attempt.acknowledged:
            return False
        await settle_confirmed(attempt)
        return True
