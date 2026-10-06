"""Place this boundary inside the dispatcher send callback, never before queuing."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from .models import DeliverySpec, DeliveryUnavailable
from .store import DeliveryStore

logger = logging.getLogger(__name__)


@dataclass
class DeliveryAttempt:
    store: DeliveryStore
    spec: DeliverySpec
    token: str
    attempted: bool = False
    acknowledged: bool = False
    state_confirmed: bool = False

    async def send(self, callback):
        """callback takes the frozen spec and must return literal True for ack.

        Cancellation/transport errors propagate; uncertain persistence never
        authorizes a second transport attempt. Redis socket timeouts are the
        injected client's responsibility.
        """
        if self.attempted:
            return False
        self.attempted = True
        boundary_uncertain = True
        try:
            result = await asyncio.to_thread(self.store.begin_send, self.spec, self.token)
            if not result.ok:
                boundary_uncertain = False
                return False
            self.acknowledged = await callback(self.spec) is True
            return self.acknowledged
        finally:
            if boundary_uncertain:
                operation = self.store.mark_sent if self.acknowledged else self.store.mark_unknown
                try:
                    result = await asyncio.to_thread(operation, self.spec.action_id, self.token)
                    self.state_confirmed = result.ok
                except DeliveryUnavailable:
                    logger.warning("Delivery persistence unresolved; never retry transport")
