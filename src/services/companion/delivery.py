"""After durable begin, recheck self authorization at the actual SDK entry."""
import asyncio

from nonebot.adapters.onebot.v11 import Message, MessageSegment
from src.services.delivery.dispatcher import dispatch, acknowledged_result
from src.services.delivery.effects.producer import production_plan, settle_confirmed
from src.services.delivery.observation import observe_plugin_output
from src.services.delivery.state import DeliveryStore, DeliveryAttempt
from src.services.memory.ledger.runtime import critical
from src.services.persistence.companion.models import spec_for
from src.services.persistence.companion.repository import CompanionRepository


class CompanionDelivery:
    def __init__(self, storage, *, schedule=dispatch, allowed=lambda user: False, queued_lease_seconds=180):
        self.repo = CompanionRepository(storage.backend)
        self.store = DeliveryStore(self.repo.client, require_effects=True, queued_lease_seconds=queued_lease_seconds)
        self.schedule, self.allowed = schedule, allowed

    async def deliver(self, bot, user, sid, *, recovery_spec=None):
        source = await asyncio.to_thread(self.repo.frozen,user,sid)
        if not source:
            return False
        spec = spec_for(user,sid,*source)
        if spec.bot_id != str(bot.self_id) or (recovery_spec is not None and spec != recovery_spec):
            return False
        if not self.allowed(user) or not await asyncio.to_thread(self.repo.guard,spec):
            return False
        operation = self.store.recover if recovery_spec is not None else self.store.claim
        claim = await asyncio.to_thread(operation,spec,plan=production_plan(spec))
        if not claim.ok:
            return False
        attempt = DeliveryAttempt(self.store,spec,claim.token)

        async def send(frozen):
            async with critical():
                # Synchronous reads under the shared gate. No await between
                # this final validation and entry to the adapter coroutine.
                if not self.allowed(user) or not self.repo.guard(frozen):
                    return False
                message = Message(MessageSegment.text(frozen.payload))
            result = await bot.send_private_msg(user_id=user,message=message)
            acknowledged = acknowledged_result(result)
            if acknowledged:
                observe_plugin_output(bot.self_id,'private',user,result,message,'companion')
            return acknowledged

        try:
            await self.schedule('private',user,lambda: attempt.send(send),category='reminder',
                                guard=lambda: self.allowed(user))
        finally:
            if not attempt.attempted:
                await asyncio.to_thread(self.store.reject_before_send,spec.action_id,claim.token)
        if attempt.acknowledged:
            await settle_confirmed(attempt)
        return attempt.acknowledged
