"""Small pages discover history work; only durable leases authorize writes."""
import asyncio
from dataclasses import dataclass
import re

from src.services.delivery.state.pagination import parse_cursor
from src.services.persistence.effects import EffectNeedsReview, EffectUnavailable
from src.services.persistence.history_commit.reconciliation import HistoryReconciliation
from .worker import HistoryWorker


@dataclass(frozen=True)
class HistoryPage:
    next_cursor: str | None
    visited: int
    outcomes: tuple[tuple[str, str], ...]


class HistoryScanner:
    def __init__(self, redis_client, *, worker=None, classifier=None):
        self.redis = redis_client
        self.worker = worker if worker is not None else HistoryWorker(redis_client)
        self.classify = classifier if classifier is not None else HistoryReconciliation(redis_client).classify

    def _scan(self, cursor: int):
        if self.redis is None:
            raise EffectUnavailable("history discovery requires Redis")
        try:
            following, keys = self.redis.execute_command(
                "SCAN", cursor, "MATCH", "mako:chat:delivery:v1:*", "COUNT", 10,
                NEVER_DECODE=True,
            )
            return int(following), sorted(
                key.decode("utf-8", errors="surrogateescape") if isinstance(key, bytes) else key
                for key in keys
            )
        except Exception as exc:
            raise EffectUnavailable("history discovery unavailable") from exc

    async def run_page(self, cursor="0:0") -> HistoryPage:
        scan_cursor, offset = parse_cursor(cursor, 10)
        following, keys = await asyncio.to_thread(self._scan, scan_cursor)
        position, visited, used, outcomes = offset, 0, 0, []
        while position < len(keys) and visited < 10 and used < 2:
            key = keys[position]
            position, visited = position + 1, visited + 1
            match = re.fullmatch(r"mako:chat:delivery:v1:([0-9a-f]{64})", key)
            if match is None:
                continue
            try:
                classification = await asyncio.to_thread(self.classify, match[1])
                if classification == "send_unknown":
                    outcomes.append((match[1], classification))
                results = await self.worker.run_action(match[1], limit=2 - used, raise_on_unavailable=True)
            except EffectNeedsReview:
                outcomes.append((match[1], "needs_review"))
                continue
            # Lease-storage outages propagate and preserve the caller's cursor.
            # A confirmed target deferral may advance; permanent receipts fence
            # any revisit without treating a stored retry as a missing result.
            used += len(results)
            outcomes.extend(results)
        next_cursor = (f"{scan_cursor}:{position}" if position < len(keys)
                       else f"{following}:0" if following else None)
        return HistoryPage(next_cursor, visited, tuple(outcomes))
