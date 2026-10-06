"""One frozen scheduled message per bot, target, task and local calendar day."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, time, timedelta

from nonebot.adapters.onebot.v11 import Message, MessageSegment

from .dispatcher import dispatch
from .effects.producer import production_plan, settle_confirmed
from .observation import observe_group_output, observe_plugin_output
from .state import DeliveryAttempt, DeliverySpec, DeliveryStore, DeliveryUnavailable

logger = logging.getLogger(__name__)


def period_deadline(period, timezone):
    naive = datetime.combine(period + timedelta(days=1), time.min)
    local = timezone.localize(naive) if hasattr(timezone, "localize") else naive.replace(tzinfo=timezone)
    return int(local.timestamp() * 1000)


class PeriodicDelivery:
    def __init__(self, redis_client, storage, dedup, *, schedule=dispatch, now=None):
        self.store = DeliveryStore(redis_client, require_effects=True)
        self.storage, self.dedup, self.schedule = storage, dedup, schedule
        self.now = now or (lambda timezone: datetime.now(timezone))

    async def deliver(self, bot, group_id, text, *, task, period, timezone, intent,
                      fingerprints=(), recovery_spec=None):
        if not group_id or self.now(timezone).date() != period:
            return False
        payload = json.dumps({"text": text, "fingerprints": list(fingerprints), "intent": intent},
                             ensure_ascii=False, sort_keys=True)
        proposed = DeliverySpec("periodic", str(bot.self_id), "group", str(group_id),
                                task, period.isoformat(), payload, period_deadline(period, timezone))
        observed = await asyncio.to_thread(self.store.inspect, proposed.action_id)
        if observed.state in {"sending", "unknown", "sent", "cancelled"}:
            return False
        frozen = observed.spec or proposed
        if recovery_spec is not None and (observed.spec is None or frozen != recovery_spec
                                         or frozen.action_id != proposed.action_id):
            return False
        claim_operation = self.store.recover if recovery_spec is not None else self.store.claim
        claim = await asyncio.to_thread(claim_operation, frozen, plan=production_plan(frozen))
        if not claim.ok:
            return False
        attempt = DeliveryAttempt(self.store, frozen, claim.token)
        body = json.loads(frozen.payload)

        async def send(spec):
            message = Message(MessageSegment.text(body["text"]))
            result = await bot.send_group_msg(group_id=int(spec.target_id), message=message)
            acknowledged = result is True or (isinstance(result, dict) and result.get("message_id") is not None)
            if acknowledged:
                observe_plugin_output(spec.bot_id, "group", spec.target_id, result, message, "news")
                try:
                    observe_group_output(spec.bot_id, int(spec.target_id), result, message, "news")
                except Exception:
                    logger.warning("Scheduled delivery acknowledged; group observation unresolved")
            return acknowledged

        try:
            decision = await asyncio.to_thread(self.dedup.check, target_type="group", target_id=group_id,
                                              intent=body["intent"], content=body["text"])
            if not decision.allowed:
                return False
            await self.schedule("group", group_id, lambda: attempt.send(send), category="news")
        finally:
            if not attempt.attempted:
                try:
                    await asyncio.to_thread(self.store.reject_before_send, frozen.action_id, claim.token)
                except DeliveryUnavailable:
                    logger.warning("Scheduled delivery reservation unresolved; no transport retry")
        if not attempt.acknowledged:
            return False
        await settle_confirmed(attempt)
        return True
