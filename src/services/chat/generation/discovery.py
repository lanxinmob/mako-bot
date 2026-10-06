"""Bounded discovery of generation costs; never resumes provider calls."""
import asyncio
from dataclasses import dataclass
import re

from src.services.delivery.state.pagination import parse_cursor
from src.services.persistence.effects import EffectNeedsReview, EffectUnavailable
from src.services.persistence.generation.index import GenerationCostIndex
from src.services.persistence.generation.models import valid_id
from .cost_worker import GenerationCostWorker


@dataclass(frozen=True)
class CostPage:
    next_cursor: str | None
    visited: int
    outcomes: tuple[tuple[str, str], ...]


class GenerationCostScanner:
    def __init__(self, redis_client, *, worker=None, index=None):
        self.redis = redis_client
        self.worker = worker if worker is not None else GenerationCostWorker(redis_client)
        self.index = index if index is not None else GenerationCostIndex(redis_client)

    async def run_due(self):
        """Consume bounded due discovery; only the existing worker grants leases."""
        members = await asyncio.to_thread(self.index.due_ids, 3)
        outcomes = []
        for member in members:
            identity = member
            if isinstance(identity, bytes):
                try:
                    identity = identity.decode("utf-8")
                except UnicodeDecodeError:
                    identity = None
            label = identity if valid_id(identity) else "invalid_member"
            try:
                outcome = await asyncio.to_thread(self.index.repair_current, member)
                if outcome == "repaired" and valid_id(identity):
                    outcome = await self.worker.run(identity)
            except EffectNeedsReview:
                outcome = "needs_review"
            outcomes.append((label, outcome))
        return CostPage(None, len(members), tuple(outcomes))

    def _scan(self, cursor):
        if self.redis is None:
            raise EffectUnavailable("generation cost discovery requires Redis")
        try:
            following, keys = self.redis.execute_command(
                "SCAN", cursor, "MATCH", "mako:generation:v1:*", "COUNT", 10,
                NEVER_DECODE=True,
            )
            # Preserve malformed names for the identity filter without failing the page.
            return int(following), sorted(
                key.decode("utf-8", errors="surrogateescape") if isinstance(key, bytes) else key
                for key in keys
            )
        except Exception as exc:
            raise EffectUnavailable("generation cost discovery unavailable") from exc

    async def repair_page(self, cursor="0:0"):
        """Rebuild discovery with a separate ten-key budget; never charge here."""
        scan_cursor, offset = parse_cursor(cursor, 10)
        following, keys = await asyncio.to_thread(self._scan, scan_cursor)
        end = min(len(keys), offset + 10)
        outcomes = []
        for key in keys[offset:end]:
            match = re.fullmatch(r"mako:generation:v1:([0-9a-f]{64})", key)
            if match is None:
                continue
            try:
                outcome = await asyncio.to_thread(self.index.repair_current, match[1])
            except EffectNeedsReview:
                outcome = "needs_review"
            outcomes.append((match[1], outcome))
        next_cursor = (f"{scan_cursor}:{end}" if end < len(keys)
                       else f"{following}:0" if following else None)
        return CostPage(next_cursor, max(0, end - offset), tuple(outcomes))

    async def run_page(self, cursor="0:0"):
        scan_cursor, offset = parse_cursor(cursor, 10)
        following, keys = await asyncio.to_thread(self._scan, scan_cursor)
        position, visited, outcomes = offset, 0, []
        while position < len(keys) and visited < 10 and len(outcomes) < 3:
            key = keys[position]
            position, visited = position + 1, visited + 1
            match = re.fullmatch(r"mako:generation:v1:([0-9a-f]{64})", key)
            if match is None:
                continue
            try:
                outcome = await self.worker.run(match[1])
            except EffectNeedsReview:
                outcome = "needs_review"
            outcomes.append((match[1], outcome))
        next_cursor = (f"{scan_cursor}:{position}" if position < len(keys)
                       else f"{following}:0" if following else None)
        return CostPage(next_cursor, visited, tuple(outcomes))
