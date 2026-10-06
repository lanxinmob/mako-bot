"""Sequential recovery of frozen, existing, unsent delivery records."""
from __future__ import annotations

import asyncio
import logging

from .listing import list_delivery_page
from .models import DeliveryUnavailable
from .store import DeliveryStore

logger = logging.getLogger(__name__)


class DeliveryRecovery:
    def __init__(self, client, handlers, *, bot_lookup, allowed):
        self.client, self.handlers = client, handlers
        self.store = DeliveryStore(client)
        self.bot_lookup, self.allowed = bot_lookup, allowed

    async def recover(self, action_id):
        """Handlers must use DeliveryStore.recover, then begin inside dispatch."""
        state = await asyncio.to_thread(self.store.inspect, action_id)
        if state.spec is None:
            return "missing"
        if state.state not in {"queued", "rejected_before_send"}:
            return "blocked"
        try:
            seconds, micros = await asyncio.to_thread(self.client.time)
        except Exception as exc:
            raise DeliveryUnavailable("recovery clock unavailable") from exc
        now = seconds * 1000 + micros // 1000
        spec = state.spec
        if now >= spec.valid_until_ms:
            return "expired"
        if state.state == "queued" and now < state.lease_until_ms:
            return "busy"
        handler = self.handlers.get(spec.kind)
        if handler is None or not self.allowed(spec):
            return "disabled"
        bot = self.bot_lookup(spec.bot_id)
        if bot is None or str(bot.self_id) != spec.bot_id:
            return "bot_unavailable"
        return "sent" if await handler(bot, spec) else "not_confirmed"

    async def run_page(self, cursor="0:0", *, limit=3):
        """One page per tick, serial handlers; cancellation is never retried here."""
        page = await asyncio.to_thread(list_delivery_page, self.client, cursor, limit=limit)
        outcomes = []
        for entry in page.entries:
            try:
                outcome = await self.recover(entry.action_id)
            except Exception:
                logger.warning("Background recovery unresolved; no immediate retry")
                outcome = "unavailable"
            outcomes.append((entry.action_id, outcome))
        return page.next_cursor, tuple(outcomes)
