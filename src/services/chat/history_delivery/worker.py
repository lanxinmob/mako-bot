"""Cancellation cannot release a history lease while its thread may still write."""
import asyncio
import logging

from src.services.persistence.effects import EffectConflict, EffectIncomplete, EffectNeedsReview, EffectUnavailable
from src.services.persistence.history_commit.session import HistoryConflict
from src.services.persistence.history_commit.tasks import HistoryEffects
from .targets import HistoryTargets


logger = logging.getLogger(__name__)


class HistoryWorker:
    def __init__(self, redis_client, *, store=None, targets=None):
        self.store = store if store is not None else HistoryEffects(redis_client)
        self.targets = targets if targets is not None else HistoryTargets(redis_client)

    async def run_task(self, action_id: str, kind: str, *, raise_on_unavailable: bool = False) -> str:
        if type(raise_on_unavailable) is not bool:
            raise ValueError("invalid history failure propagation mode")
        lease = await asyncio.to_thread(self.store.claim, action_id, kind)
        if lease is None:
            return "not_claimed"
        retry = False
        try:
            outcome = await asyncio.to_thread(self.targets.apply, lease)
            if outcome not in {"applied", "already_applied"}:
                outcome = "invalid_payload"
        except HistoryConflict:
            outcome = "history_conflict"
        except EffectUnavailable:
            outcome, retry = "unavailable", True
        except EffectConflict:
            outcome = "conflict"
        except EffectIncomplete:
            outcome = "target_incomplete"
        except (EffectNeedsReview, ValueError, TypeError, KeyError, OverflowError):
            outcome = "invalid_payload"
        except Exception:
            outcome = "execution_error"
        # CancelledError bypasses settlement. Even a cancelled to_thread await
        # may have a live writer; retain the lease until its deadline.
        try:
            confirmed = await asyncio.to_thread(self.store.defer if retry else self.store.finish,
                                                 *([lease] if retry else [lease, outcome]))
        except EffectUnavailable:
            logger.warning("Chat history settlement unconfirmed; retained without resending")
            if raise_on_unavailable:
                raise
            return "settlement_unconfirmed"
        except EffectNeedsReview:
            return "needs_review" if raise_on_unavailable else "settlement_unconfirmed"
        return outcome if confirmed else "settlement_unconfirmed"

    async def run_action(self, action_id: str, *, limit=2,
                         raise_on_unavailable: bool = False) -> tuple[tuple[str, str], ...]:
        if type(limit) is not int or not 1 <= limit <= 2:
            raise ValueError("invalid history work limit")
        if type(raise_on_unavailable) is not bool:
            raise ValueError("invalid history failure propagation mode")
        snapshot = await asyncio.to_thread(self.store.inspect, action_id)
        if snapshot is None or snapshot.delivery.state != "sent":
            return ()
        outcomes = []
        unavailable = None
        for task in snapshot.tasks:
            if task.state not in {"pending", "leased", "retry_wait"}:
                continue
            try:
                outcome = await self.run_task(action_id, task.kind,
                                              raise_on_unavailable=raise_on_unavailable)
            except EffectUnavailable as exc:
                if unavailable is None:
                    unavailable = exc
                outcome = "unconfirmed"
            except EffectNeedsReview:
                outcome = "needs_review" if raise_on_unavailable else "unconfirmed"
            outcomes.append((task.kind, outcome))
            if len(outcomes) >= limit:
                break
        # Finish this bounded set of independent attempts before pausing the
        # scanner. Do not let a lease-storage outage become a successful page.
        if raise_on_unavailable and unavailable is not None:
            raise unavailable
        return tuple(outcomes)
