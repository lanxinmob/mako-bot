"""Bounded discovery of stored action effects; scanning never grants transport."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import re

from src.services.persistence.effects import EffectNeedsReview, EffectUnavailable
from ..state.pagination import parse_cursor
from ..state.effect_legacy import classify_legacy_sent
from .worker import EffectWorker


@dataclass(frozen=True)
class EffectPage:
    next_cursor: str | None
    visited: int
    outcomes: tuple[tuple[str, str], ...]


class EffectScanner:
    def __init__(self, redis_client, *, worker=None):
        self.redis = redis_client
        self.worker = worker if worker is not None else EffectWorker(redis_client)

    def _scan(self, cursor, count):
        if self.redis is None:
            raise EffectUnavailable("effect discovery requires Redis")
        try:
            following, keys = self.redis.scan(cursor=cursor, match="mako:delivery:v1:*", count=count)
            return int(following), sorted(key.decode() if isinstance(key, bytes) else key for key in keys)
        except Exception as exc:
            raise EffectUnavailable("effect discovery unavailable") from exc

    async def run_page(self, cursor="0:0", *, key_limit=10, task_limit=3):
        scan_cursor, offset = parse_cursor(cursor, key_limit)
        if key_limit > 10 or type(task_limit) is not int or not 1 <= task_limit <= 3:
            raise ValueError("invalid effect discovery budget")
        following, keys = await asyncio.to_thread(self._scan, scan_cursor, key_limit)
        position, visited, used, outcomes = offset, 0, 0, []
        while position < len(keys) and visited < key_limit and used < task_limit:
            key = keys[position]
            position, visited = position + 1, visited + 1
            match = re.fullmatch(r"mako:delivery:v1:([0-9a-f]{64})", key)
            if match is None:
                continue
            try:
                results = await self.worker.run_action(match[1], limit=task_limit - used)
            except EffectNeedsReview:
                try:
                    classification = await asyncio.to_thread(classify_legacy_sent, self.redis, match[1])
                except EffectNeedsReview:
                    classification = "needs_review"
                outcomes.append((match[1], classification))
                continue
            # A discovery/read outage propagates so the caller keeps its cursor.
            # Previously applied targets are safe to revisit under their IDs.
            used += len(results)
            outcomes.extend(results)
        next_cursor = (f"{scan_cursor}:{position}" if position < len(keys)
                       else f"{following}:0" if following else None)
        return EffectPage(next_cursor, visited, tuple(outcomes))
