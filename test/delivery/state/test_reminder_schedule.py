import asyncio
from datetime import timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from apscheduler.jobstores.base import JobLookupError

from src.services.delivery.reminder_schedule import ReminderSchedule
from src.services.persistence.reminder_state import ReminderPersistenceUnavailable
from test.autonomy.test_pending_atomic import isolated_redis
from test.delivery.state.test_reminder_source import record


def runtime(client):
    jobs = {}
    scheduler = SimpleNamespace(timezone=timezone.utc, get_job=jobs.get)

    def add(func, trigger, **kwargs):
        jobs[kwargs["id"]] = SimpleNamespace(func=func, args=kwargs["args"], run_date=kwargs["run_date"])

    scheduler.add_job = Mock(side_effect=add)
    scheduler.remove_job = Mock(side_effect=lambda job_id: jobs.pop(job_id))
    service = ReminderSchedule(client, scheduler, AsyncMock(), lock=asyncio.Lock())
    return service, scheduler, jobs


@pytest.mark.asyncio
async def test_registration_failure_keeps_durable_intent_and_restart_restores(isolated_redis):
    service, scheduler, jobs = runtime(isolated_redis)
    add = scheduler.add_job.side_effect
    scheduler.add_job.side_effect = RuntimeError("scheduler unavailable")
    change = await service.create(record(isolated_redis), "99")
    assert change.mutation.ok and not change.cache_confirmed
    saved = service.source.load("fixture")
    scheduler.add_job.side_effect = add
    await service.restore()
    assert jobs["fixture"].args[1] == saved.revision
    assert jobs["fixture"].run_date.timestamp() == saved.record.remind_time.timestamp()
    assert service.source.load("fixture") == saved


@pytest.mark.asyncio
@pytest.mark.parametrize("missing_job", [False, True])
async def test_modify_retains_id_and_replaces_revision_without_old_job_removal(isolated_redis, missing_job):
    service, scheduler, jobs = runtime(isolated_redis)
    old = (await service.create(record(isolated_redis), "99")).mutation.snapshot
    if missing_job:
        jobs.clear()
    updated = await service.replace(old, old.record.model_copy(update={"content": "updated"}), "99")
    assert updated.mutation.ok and updated.cache_confirmed
    assert set(jobs) == {"fixture"}
    assert jobs["fixture"].args[1] != old.revision
    scheduler.remove_job.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [JobLookupError("fixture"), RuntimeError("unavailable")])
async def test_cancel_durable_first_even_if_cache_removal_fails(isolated_redis, failure):
    service, scheduler, jobs = runtime(isolated_redis)
    old = (await service.create(record(isolated_redis), "99")).mutation.snapshot
    scheduler.remove_job.side_effect = failure
    change = await service.cancel(old)
    assert change.mutation.ok
    assert change.cache_confirmed is isinstance(failure, JobLookupError)
    assert service.source.load("fixture") is None


@pytest.mark.asyncio
async def test_restore_preserves_overdue_and_migrates_only_future_legacy(isolated_redis):
    service, scheduler, jobs = runtime(isolated_redis)
    for name, delta in [("future", 3600), ("past", -60)]:
        isolated_redis.hset("reminders", name, record(isolated_redis, job_id=name, delta=delta).model_dump_json())
    original = isolated_redis.hget("reminders", "past")
    await service.restore()
    assert set(jobs) == {"future"}
    assert service.source.load("future").revision
    assert service.source.load("past").revision == ""
    assert isolated_redis.hget("reminders", "past") == original


@pytest.mark.asyncio
async def test_no_cache_mutation_on_redis_outage():
    service, scheduler, jobs = runtime(None)
    with pytest.raises(ReminderPersistenceUnavailable):
        await service.restore()
    assert not jobs
    scheduler.add_job.assert_not_called()
    scheduler.remove_job.assert_not_called()
