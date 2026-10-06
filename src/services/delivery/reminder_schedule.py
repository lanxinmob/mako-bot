"""Persist reminder changes before updating the replaceable scheduler cache."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

from apscheduler.jobstores.base import JobLookupError

from src.services.persistence.reminder_state import ReminderStateStore
from .reminder_delivery import reminder_spec
from .state import DeliveryStore
from .state.pagination import parse_cursor

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScheduledChange:
    mutation: object
    cache_confirmed: bool


class ReminderSchedule:
    def __init__(self, redis_client, scheduler, callback, *, lock, wait_seconds=120):
        self.source = ReminderStateStore(redis_client)
        self.scheduler, self.callback = scheduler, callback
        self.lock, self.wait_seconds = lock, max(0, wait_seconds)

    def deadline(self, snapshot):
        intent = snapshot.intent
        return int(intent["remind_at_ms"] + (intent["grace_seconds"] + self.wait_seconds) * 1000)

    def action_key(self, snapshot):
        if not snapshot.revision or not snapshot.intent.get("bot_id"):
            return ""
        return DeliveryStore.key(reminder_spec(snapshot, valid_until_ms=self.deadline(snapshot)).action_id)

    def _cache(self, job_id, snapshot):
        try:
            if snapshot is None:
                job = self.scheduler.get_job(job_id)
                if job is not None and job.func == self.callback:
                    self.scheduler.remove_job(job_id)
            else:
                args = (job_id, snapshot.revision, self.deadline(snapshot))
                job = self.scheduler.get_job(job_id)
                if job is not None and job.func == self.callback and tuple(job.args) == args:
                    return True
                # Epoch timestamps preserve the persisted instant for both
                # naive legacy dates and timezone-aware new dates.
                run_date = datetime.fromtimestamp(snapshot.intent["remind_at_ms"] / 1000,
                                                 tz=self.scheduler.timezone)
                self.scheduler.add_job(self.callback, "date", run_date=run_date, args=args,
                    id=job_id, misfire_grace_time=int(snapshot.intent["grace_seconds"]),
                    replace_existing=True)
            return True
        except JobLookupError:
            return snapshot is None
        except Exception:
            logger.warning("Reminder persisted; scheduler cache update unconfirmed")
            return False

    async def create(self, record, bot_id):
        async with self.lock:
            result = await asyncio.to_thread(self.source.create, record, bot_id=bot_id)
            cached = result.ok and self._cache(record.reminder_id, result.snapshot)
            return ScheduledChange(result, cached)

    async def replace(self, snapshot, record, bot_id):
        async with self.lock:
            result = await asyncio.to_thread(self.source.replace, snapshot, record,
                                            bot_id=bot_id, action_key=self.action_key(snapshot))
            cached = result.ok and self._cache(record.reminder_id, result.snapshot)
            return ScheduledChange(result, cached)

    async def cancel(self, snapshot):
        async with self.lock:
            result = await asyncio.to_thread(self.source.cancel, snapshot,
                                            action_key=self.action_key(snapshot))
            cached = result.ok and self._cache(snapshot.record.reminder_id, None)
            return ScheduledChange(result, cached)

    async def restore(self):
        """Recover future sources only; never infer an overdue item was unsent."""
        restored = 0
        for intents in (False, True):
            cursor = "0:0"
            while True:
                cursor, count = await self.restore_page(cursor, intents=intents)
                restored += count
                if cursor is None:
                    break
        return restored

    async def restore_page(self, cursor="0:0", *, intents=False, limit=10):
        """Bound scheduler work even when HSCAN returns an oversized batch."""
        scan_cursor, offset = parse_cursor(cursor, limit)
        following, ids = await asyncio.to_thread(self.source.scan_ids, scan_cursor,
                                                intents=intents, count=limit)
        ids = sorted(ids)
        end = min(len(ids), offset + limit)
        next_cursor = (f"{scan_cursor}:{end}" if end < len(ids)
                       else f"{following}:0" if following else None)
        restored = 0
        for job_id in ids[offset:end]:
            async with self.lock:
                snapshot = await asyncio.to_thread(self.source.load, job_id)
                if snapshot is None:
                    self._cache(job_id, None)
                    continue
                if snapshot.record.remind_time.timestamp() <= datetime.now().timestamp():
                    continue
                if not snapshot.revision:
                    result = await asyncio.to_thread(self.source.migrate_future, snapshot)
                    if not result.ok:
                        continue
                    snapshot = result.snapshot
                if snapshot.intent.get("operation") == "upsert":
                    restored += int(self._cache(job_id, snapshot))
        return next_cursor, restored
