"""Recover durable due intents; no repeated invitations or unknown transport."""
import asyncio
import json

from src.services.delivery.state import DeliveryStore
from src.services.memory.ledger.runtime import critical, confirmed_thread
from src.services.persistence.companion.models import spec_for
from src.services.persistence.companion.lifecycle import update
from src.services.persistence.companion.repository import PREFIX
from .delivery import CompanionDelivery


class CompanionScanner:
    def __init__(self, service, *, allowed, bot_lookup, schedule=None):
        self.service,self.repo = service,service.repo
        self.allowed,self.bot_lookup,self.schedule = allowed,bot_lookup,schedule
        self.offset = 0

    async def run(self, limit=20):
        # Startup/query can finish only an already accepted immutable operation.
        for user in await asyncio.to_thread(self.repo.users):
            await self.service.reconcile(user)
            for plan in await asyncio.to_thread(self.repo.list,user):
                async with critical():
                    await confirmed_thread(update,self.repo,user,plan['plan_id'])
        now = await asyncio.to_thread(self.repo.now)
        due = await asyncio.to_thread(self.repo.client.zrangebyscore,PREFIX+'due','-inf',now,
                                      start=self.offset,num=limit)
        self.offset = self.offset+len(due) if len(due) == limit else 0
        outcomes = []
        for value in due:
            user,pid,step = value.split(':')
            user = int(user)
            sid = pid+':'+step
            frozen = await asyncio.to_thread(self.repo.frozen,user,sid)
            if not frozen:
                continue
            spec = spec_for(user,sid,*frozen)
            plan = await asyncio.to_thread(self.repo.get,user,pid)
            body = json.loads(frozen[0])
            transport = await asyncio.to_thread(DeliveryStore(self.repo.client).inspect,spec.action_id)
            if transport.state in {'sending','sent','unknown'}:
                outcomes.append((sid,transport.state))
                continue
            reason = ''
            bot = self.bot_lookup(spec.bot_id)
            if not self.allowed(user):
                reason = 'permission'
            elif bot is None:
                reason = 'bot_unavailable'
            elif self.repo.state(user)['revision'] != body['memory_revision']:
                reason = 'memory_changed'
            elif step == 'review':
                reminder = plan['steps']['reminder']
                prior = await asyncio.to_thread(DeliveryStore(self.repo.client).inspect,reminder['action_id'])
                if not reminder['source_complete'] or prior.state != 'sent':
                    reason = 'reminder_unconfirmed'
            async with critical():
                await confirmed_thread(lambda: update(self.repo,user,pid,step=step,reason=reason))
            if reason or not await asyncio.to_thread(self.repo.guard,spec):
                outcomes.append((sid,reason or 'expired'))
                continue
            options = {'allowed':self.allowed}
            if self.schedule is not None:
                options['schedule'] = self.schedule
            delivered = await CompanionDelivery(self.service.storage,**options).deliver(
                bot,user,sid,recovery_spec=transport.spec if transport.state else None)
            outcomes.append((sid,'sent' if delivered else 'not_confirmed'))
        return outcomes
