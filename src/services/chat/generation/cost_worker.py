"""Retry frozen cost writes, never provider invocations or message delivery."""
import asyncio
from datetime import datetime

from src.services.persistence.effects import EffectConflict, EffectNeedsReview, EffectUnavailable, EffectWriter
from src.services.persistence.generation.costs import GenerationCosts


class GenerationCostWorker:
    def __init__(self, redis_client, *, costs=None, writer=None):
        self.costs = costs if costs is not None else GenerationCosts(redis_client)
        self.writer = writer if writer is not None else EffectWriter(redis_client)

    async def run(self, attempt_id):
        lease = await asyncio.to_thread(self.costs.claim, attempt_id)
        if lease is None:
            return "not_claimed"
        try:
            outcome = await asyncio.to_thread(self.writer.consume_cost,
                lease.spec.cost_effect_id, lease.spec.user_id, lease.amount,
                at=datetime.strptime(lease.spec.cost_day, "%Y%m%d"))
        except EffectUnavailable:
            outcome = "unavailable"
        except EffectConflict:
            outcome = "conflict"
        except Exception:
            outcome = "needs_review"
        # Cancellation does not release a lease whose target thread may still run.
        if not isinstance(outcome, str) or outcome not in {"applied", "already_applied", "unavailable", "conflict", "needs_review"}:
            outcome = "needs_review"
        try:
            confirmed = await asyncio.to_thread(self.costs.finish, lease, outcome)
        except (EffectUnavailable, EffectNeedsReview):
            return "settlement_unconfirmed"
        return outcome if confirmed else "settlement_unconfirmed"
