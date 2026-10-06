"""A persisted started receipt survives loss of a partial script's error."""
import asyncio
import json
import threading
from types import SimpleNamespace

import pytest
from redis.exceptions import ResponseError

from src.services.delivery.effects.store import EffectStore
from src.services.delivery.effects.targets import EffectTargets
from src.services.delivery.effects.worker import EffectWorker
from src.services.persistence.effects import EffectWriter
from src.services.persistence.effects.source import SourceEffectWriter
from test.autonomy.test_pending_atomic import isolated_redis
from test.autonomy.owner_loader import load_owner
from test.delivery.effects.test_effect_leases import activate, rewrite_task


@pytest.mark.asyncio
@pytest.mark.parametrize("index,key", [(0, "outbound:ledger:group:1"), (1, "all_memory")])
@pytest.mark.parametrize("mode", ["control", "settle_failure", "cancel", "lost_error"])
async def test_partial_append_never_replays_after_error_loss(isolated_redis, index, key, mode):
    client = isolated_redis
    spec, store = activate(client)
    task = store.inspect(spec.action_id).tasks[index]
    entered, release, ended = threading.Event(), threading.Event(), threading.Event()

    def partial(*args):
        script = args[0].replace("redis.call('LTRIM', KEYS[2], -p.max_records, -1)",
                                 "error('injected failure after RPUSH')")
        assert script != args[0]
        try:
            return client.eval(script, *args[1:])
        except ResponseError:
            if mode == "lost_error":
                raise ConnectionError("lost server error response")
            if mode == "cancel":
                entered.set()
                assert release.wait(5)
            raise
        finally:
            ended.set()

    def fail_settle(*args):
        if args[6] == "finish":
            raise ConnectionError("failure before settlement")
        return client.eval(*args)

    targets = EffectTargets(client)
    targets.writer = EffectWriter(SimpleNamespace(eval=partial))
    worker_store = EffectStore(SimpleNamespace(get=client.get, eval=fail_settle)) if mode == "settle_failure" else store
    worker = EffectWorker(client, store=worker_store, targets=targets)
    if mode == "cancel":
        running = asyncio.create_task(worker.run_task(spec.action_id, task.effect_id))
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            running.cancel()
            with pytest.raises(asyncio.CancelledError):
                await running
        finally:
            release.set()
            assert await asyncio.to_thread(ended.wait, 3)
    else:
        first = await worker.run_task(spec.action_id, task.effect_id)
        assert first == {"control": "invalid_payload", "lost_error": "unavailable",
                         "settle_failure": "settlement_unconfirmed"}[mode]
    receipt = "mako:delivery:v1:effect:" + task.effect_id
    marker = client.get(receipt)
    assert marker.startswith("started:") and client.llen(key) == 1
    rewrite_task(client, spec, task.effect_id, lease_until_ms=0, next_attempt_at_ms=0)
    outcome = await EffectWorker(client).run_task(spec.action_id, task.effect_id)
    assert outcome == ("not_claimed" if mode == "control" else "target_incomplete")
    assert client.llen(key) == 1 and client.get(receipt) == marker and client.ttl(receipt) == -1
    assert store.inspect(spec.action_id).tasks[index].state == "needs_review"
    if mode != "control":
        assert store.inspect(spec.action_id).tasks[index].result_code == "target_incomplete"
        feedback = load_owner().process_delivery_command.__globals__["effect_feedback"](client, spec.action_id)
        assert "目标可能已部分写入，禁止自动重试" in feedback


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["followup", "reminder"])
async def test_partial_source_completion_keeps_permanent_barrier(isolated_redis, kind):
    client = isolated_redis
    spec, store = activate(client, kind=kind)
    task = store.inspect(spec.action_id).tasks[0]
    stop = ("redis.call('ZREM', KEYS[5], spec.target_id .. ':' .. spec.business_id)"
            if kind == "followup" else "redis.call('HSET', KEYS[5], spec.source_field, completed)")

    def partial(*args):
        script = args[0].replace(stop, "error('injected source partial write')")
        assert script != args[0]
        try:
            return client.eval(script, *args[1:])
        except ResponseError:
            raise ConnectionError("lost source error response")

    targets = EffectTargets(client)
    targets.sources = SourceEffectWriter(SimpleNamespace(eval=partial))
    assert await EffectWorker(client, targets=targets).run_task(spec.action_id, task.effect_id) == "unavailable"
    receipt = "mako:delivery:v1:effect-source:" + task.effect_id
    assert json.loads(client.get(receipt))["result"] == "started"
    source_before = client.hget(spec.source_key, spec.source_field)
    rewrite_task(client, spec, task.effect_id, next_attempt_at_ms=0)
    assert await EffectWorker(client).run_task(spec.action_id, task.effect_id) == "target_incomplete"
    assert client.hget(spec.source_key, spec.source_field) == source_before
    assert json.loads(client.get(receipt))["result"] == "started"
    assert client.ttl(receipt) == -1


@pytest.mark.asyncio
async def test_old_thread_starting_after_new_lease_commit_does_not_append(isolated_redis):
    client = isolated_redis
    spec, store = activate(client)
    task = store.inspect(spec.action_id).tasks[1]
    entered, release, ended = threading.Event(), threading.Event(), threading.Event()
    real = EffectTargets(client)

    def delayed(lease):
        entered.set()
        try:
            assert release.wait(5)
            return real.apply(lease)
        finally:
            ended.set()

    running = asyncio.create_task(EffectWorker(client, targets=SimpleNamespace(apply=delayed)).run_task(
        spec.action_id, task.effect_id))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        rewrite_task(client, spec, task.effect_id, lease_until_ms=0)
        assert await EffectWorker(client).run_task(spec.action_id, task.effect_id) == "applied"
    finally:
        release.set()
        assert await asyncio.to_thread(ended.wait, 3)
    assert await running == "settlement_unconfirmed"
    assert client.llen("all_memory") == 1
