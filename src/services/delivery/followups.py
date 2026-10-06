"""Version-bound relationship delivery through the shared outbound scheduler."""
from __future__ import annotations

import asyncio
import logging

from nonebot.adapters.onebot.v11 import Message

from src.services.persistence.followups import FollowupSource, revision_key
from .dispatcher import dispatch
from .observation import observe_plugin_output
from .effects.producer import production_plan, settle_confirmed
from .state import DeliveryAttempt, DeliverySpec, DeliveryStore, DeliveryUnavailable

logger = logging.getLogger(__name__)


class FollowupDelivery:
    def __init__(self, redis_client, dedup, *, schedule=dispatch):
        self.source = FollowupSource(redis_client)
        self.store = DeliveryStore(redis_client, queued_lease_seconds=180, require_effects=True)
        self.dedup, self.schedule = dedup, schedule

    async def deliver(self, bot, user_id, memory_id, *, recovery_spec=None):
        snapshot = await asyncio.to_thread(self.source.load, user_id, memory_id)
        if snapshot is None:
            return False
        memory = snapshot.memory
        text = f"之前说过要跟进这件事：{memory.content}\n现在进展怎么样啦？"
        decision = await asyncio.to_thread(self.dedup.check, target_type="private",
                                          target_id=user_id, intent="reminder", content=text)
        if not decision.allowed:
            return False
        spec = DeliverySpec("followup", str(bot.self_id), "private", str(user_id), memory_id,
                            snapshot.revision, text, 2**52, f"relationship:{user_id}",
                            memory_id, snapshot.digest, revision_key(user_id))
        if recovery_spec is not None and spec != recovery_spec:
            return False
        claim_operation = self.store.recover if recovery_spec is not None else self.store.claim
        claim = await asyncio.to_thread(claim_operation, spec, plan=production_plan(spec))
        if not claim.ok:
            return False
        attempt = DeliveryAttempt(self.store, spec, claim.token)

        async def send(frozen):
            result = await bot.send_private_msg(user_id=int(frozen.target_id), message=Message(frozen.payload))
            acknowledged = result is True or (isinstance(result, dict) and result.get("message_id") is not None)
            if acknowledged:
                observe_plugin_output(frozen.bot_id, "private", frozen.target_id, result,
                                      Message(frozen.payload), "reminder")
            return acknowledged

        try:
            await self.schedule("private", user_id, lambda: attempt.send(send), category="reminder")
        finally:
            if not attempt.attempted:
                try:
                    await asyncio.to_thread(self.store.reject_before_send, spec.action_id, claim.token)
                except DeliveryUnavailable:
                    logger.warning("Unsent followup reservation unresolved; lease may recover it")
        if not attempt.acknowledged:
            return False
        await settle_confirmed(attempt)
        return True
