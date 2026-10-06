"""Bounded post-delivery work; cancellation leaves leases for safe recovery."""
from __future__ import annotations

import asyncio
import logging

from src.services.persistence.effects import EffectConflict, EffectIncomplete, EffectNeedsReview, EffectUnavailable
from .store import EffectStore
from .targets import EffectTargets

logger = logging.getLogger(__name__)


class EffectWorker:
    def __init__(self, redis_client, *, store=None, targets=None):
        self.store = store if store is not None else EffectStore(redis_client)
        self.targets = targets if targets is not None else EffectTargets(redis_client)

    async def run_task(self, action_id, effect_id):
        lease = await asyncio.to_thread(self.store.claim, action_id, effect_id)
        if lease is None:
            return "not_claimed"
        retry = False
        try:
            outcome = await asyncio.to_thread(self.targets.apply, lease)
        except EffectUnavailable:
            outcome, retry = "unavailable", True
        except EffectConflict:
            outcome = "conflict"
        except EffectIncomplete:
            outcome = "target_incomplete"
        except (EffectNeedsReview, ValueError, TypeError, KeyError):
            outcome = "invalid_payload"
        except Exception:
            # Unknown program/server failure may follow a partial target write.
            outcome = "execution_error"
        # CancelledError is not caught above. A cancelled to_thread await may
        # leave its thread alive: never release or defer that lease prematurely.
        try:
            confirmed = await asyncio.to_thread(
                self.store.defer if retry else self.store.finish,
                *([lease] if retry else [lease, outcome]),
            )
        except (EffectUnavailable, EffectNeedsReview):
            logger.warning("Effect task settlement unconfirmed; retained for reconciliation")
            return "settlement_unconfirmed"
        return outcome if confirmed else "settlement_unconfirmed"

    async def run_action(self, action_id, *, limit=3):
        if type(limit) is not int or not 1 <= limit <= 3:
            raise ValueError("invalid effect work limit")
        snapshot = await asyncio.to_thread(self.store.inspect, action_id)
        if snapshot is None:
            return ()
        outcomes = []
        for task in snapshot.tasks:
            if task.state not in {"pending", "leased", "retry_wait"}:
                continue
            try:
                result = await self.run_task(action_id, task.effect_id)
            except (EffectUnavailable, EffectNeedsReview):
                result = "unconfirmed"
            outcomes.append((task.effect_id, result))
            if len(outcomes) >= limit:
                break
        return tuple(outcomes)
