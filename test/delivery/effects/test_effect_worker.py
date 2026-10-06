"""Idempotent target/lease integration, cancellation and independent failures."""
import asyncio
import json
import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.models.schemas import ChatRecord, OutboundMessageRecord
from src.services.delivery.effects.store import EffectStore
from src.services.delivery.effects.targets import EffectTargets
from src.services.delivery.effects.worker import EffectWorker
from src.services.delivery.state import DeliveryStore
from src.services.persistence.effects import EffectWriter
from test.autonomy.test_pending_atomic import isolated_redis
from test.delivery.effects.test_effect_leases import activate, rewrite_task


@pytest.mark.asyncio
async def test_periodic_tasks_write_frozen_records_and_complete_once(isolated_redis):
    client = isolated_redis
    spec, store = activate(client)
    worker = EffectWorker(client)
    results = await worker.run_action(spec.action_id)
    assert [result for _, result in results] == ["applied"] * 3
    action = json.loads(client.get(DeliveryStore.key(spec.action_id)))
    assert action["effects_state"] == "complete"
    sent = action["sent_recorded_at_ms"]
    expected = datetime.fromtimestamp(sent / 1000, tz=timezone(timedelta(hours=8))).replace(tzinfo=None)
    history = ChatRecord.model_validate_json(client.lindex("all_memory", 0))
    outbound = OutboundMessageRecord.model_validate_json(client.lindex("outbound:ledger:group:1", 0))
    assert history.time == expected and outbound.created_at == expected
    assert outbound.message_id == store.inspect(spec.action_id).tasks[0].effect_id
    assert float(client.hget("news:sent", "fp")) == sent / 1000
    assert await worker.run_action(spec.action_id) == ()
    assert client.llen("all_memory") == client.llen("outbound:ledger:group:1") == 1


@pytest.mark.asyncio
async def test_one_bad_target_does_not_block_other_tasks(isolated_redis):
    client = isolated_redis
    spec, store = activate(client)
    client.set("all_memory", "wrong type")
    results = await EffectWorker(client).run_action(spec.action_id)
    assert [code for _, code in results] == ["applied", "invalid_payload", "applied"]
    tasks = store.inspect(spec.action_id).tasks
    assert [task.state for task in tasks] == ["complete", "needs_review", "complete"]
    assert client.get("all_memory") == "wrong type"
    assert json.loads(client.get(DeliveryStore.key(spec.action_id)))["effects_state"] == "needs_review"


@pytest.mark.asyncio
async def test_target_commit_response_lost_retries_identical_effect(isolated_redis):
    client = isolated_redis
    spec, store = activate(client)
    count = 0

    def lost_once(*args):
        nonlocal count
        result = client.eval(*args)
        count += 1
        if count == 1:
            raise ConnectionError("synthetic response loss")
        return result

    targets = EffectTargets(client)
    targets.writer = EffectWriter(SimpleNamespace(eval=lost_once))
    worker = EffectWorker(client, targets=targets)
    assert [code for _, code in await worker.run_action(spec.action_id)] == ["unavailable", "applied", "applied"]
    task = store.inspect(spec.action_id).tasks[0]
    assert task.state == "retry_wait" and client.llen("outbound:ledger:group:1") == 1
    rewrite_task(client, spec, task.effect_id, next_attempt_at_ms=0)
    assert await worker.run_action(spec.action_id) == ((task.effect_id, "already_applied"),)
    assert client.llen("outbound:ledger:group:1") == 1


@pytest.mark.asyncio
async def test_finish_commit_response_lost_does_not_repeat_target(isolated_redis):
    client = isolated_redis
    spec, _ = activate(client, kind="reminder")

    def lose_finish(*args):
        result = client.eval(*args)
        if args[6] == "finish":
            raise ConnectionError("synthetic finish response loss")
        return result

    store = EffectStore(SimpleNamespace(get=client.get, eval=lose_finish))
    worker = EffectWorker(client, store=store)
    outcomes = await worker.run_action(spec.action_id)
    assert outcomes[0][1] == "settlement_unconfirmed"
    assert not client.hexists("reminders", spec.business_id)
    assert await worker.run_action(spec.action_id) == ()
    assert store.inspect(spec.action_id).tasks[0].state == "complete"


@pytest.mark.asyncio
async def test_cancelled_await_leaves_running_target_thread_and_lease_intact(isolated_redis):
    client = isolated_redis
    spec, store = activate(client, kind="reminder")
    started, release, ended = threading.Event(), threading.Event(), threading.Event()
    real = EffectTargets(client)

    def slow_target(lease):
        started.set()
        try:
            if not release.wait(5):
                raise RuntimeError("synthetic timeout")
            return real.apply(lease)
        finally:
            ended.set()

    worker = EffectWorker(client, targets=SimpleNamespace(apply=slow_target))
    running = asyncio.create_task(worker.run_action(spec.action_id))
    try:
        assert await asyncio.to_thread(started.wait, 3)
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
        leased = store.inspect(spec.action_id).tasks[0]
        assert leased.state == "leased"
        assert store.claim(spec.action_id, leased.effect_id) is None
    finally:
        release.set()
        assert await asyncio.to_thread(ended.wait, 3)
    rewrite_task(client, spec, leased.effect_id, lease_until_ms=0)
    assert await EffectWorker(client).run_action(spec.action_id) == ((leased.effect_id, "already_applied"),)
    assert store.inspect(spec.action_id).tasks[0].state == "complete"


@pytest.mark.asyncio
async def test_owner_unknown_time_only_completes_original_source(isolated_redis):
    client = isolated_redis
    spec, store = activate(client, kind="followup", owner=True)
    results = await EffectWorker(client).run_action(spec.action_id)
    assert len(results) == 1 and results[0][1] == "applied"
    assert not client.exists("outbound:ledger:private:7")
    assert [task.state for task in store.inspect(spec.action_id).tasks] == ["complete", "needs_review"]
    assert json.loads(client.get(DeliveryStore.key(spec.action_id)))["delivered_at_ms"] is None
