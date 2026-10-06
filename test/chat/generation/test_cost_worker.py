"""Frozen-day idempotent cost consumption with cancellation and fencing."""
import asyncio
import json
import threading
from types import SimpleNamespace

import pytest

from src.services.chat.generation.cost_worker import GenerationCostWorker
from src.services.persistence.effects import EffectWriter
from src.services.persistence.generation.costs import GenerationCosts
from test.chat.generation.test_store import attempt
from test.autonomy.test_pending_atomic import isolated_redis


def completed(attempt):
    client, store, spec = attempt
    token = store.start(spec)
    store.complete(spec, token, .05)
    return client, store, spec


def expire(client, store, spec, field):
    key = store.key(spec.attempt_id)
    value = json.loads(client.get(key))
    value[field] = 0
    client.set(key, json.dumps(value))


@pytest.mark.asyncio
async def test_concurrent_workers_charge_frozen_date_once(attempt):
    client, store, spec = completed(attempt)
    worker = GenerationCostWorker(client)
    results = await asyncio.gather(worker.run(spec.attempt_id), worker.run(spec.attempt_id))
    assert results.count("applied") == 1
    assert await worker.run(spec.attempt_id) == "not_claimed"
    assert float(client.get("cost:global:20260927")) == pytest.approx(.05)
    assert float(client.get("cost:user:7:20260927")) == pytest.approx(.05)
    assert GenerationCosts(client).inspect(spec.attempt_id).state == "complete"
    assert client.ttl(store.key(spec.attempt_id)) == -1


@pytest.mark.asyncio
async def test_target_response_loss_uses_receipt_on_retry(attempt):
    client, store, spec = completed(attempt)

    def lost(*args):
        client.eval(*args)
        raise ConnectionError("synthetic target response loss")

    worker = GenerationCostWorker(client, writer=EffectWriter(SimpleNamespace(eval=lost)))
    assert await worker.run(spec.attempt_id) == "unavailable"
    assert await worker.run(spec.attempt_id) == "not_claimed"
    expire(client, store, spec, "cost_next_attempt_at_ms")
    assert await GenerationCostWorker(client).run(spec.attempt_id) == "already_applied"
    assert float(client.get("cost:global:20260927")) == pytest.approx(.05)


@pytest.mark.asyncio
async def test_finish_response_loss_and_old_token_cannot_change_completed(attempt):
    client, store, spec = completed(attempt)
    costs = GenerationCosts(client)
    first = costs.claim(spec.attempt_id)
    expire(client, store, spec, "cost_lease_until_ms")
    second = costs.claim(spec.attempt_id)
    assert first.token != second.token
    assert not costs.finish(first, "needs_review")
    assert costs.finish(second, "unavailable")
    expire(client, store, spec, "cost_next_attempt_at_ms")

    def lost(script, numkeys, *keys_and_args):
        result = client.eval(script, numkeys, *keys_and_args)
        operation = keys_and_args[numkeys + 1]
        if operation == "finish":
            raise ConnectionError("synthetic settlement response loss")
        return result

    worker = GenerationCostWorker(client, costs=GenerationCosts(SimpleNamespace(get=client.get, eval=lost)))
    assert await worker.run(spec.attempt_id) == "settlement_unconfirmed"
    assert await GenerationCostWorker(client).run(spec.attempt_id) == "not_claimed"
    assert float(client.get("cost:global:20260927")) == pytest.approx(.05)


@pytest.mark.asyncio
async def test_bad_counter_stops_automatic_retry_without_partial_charge(attempt):
    client, _, spec = completed(attempt)
    client.set("cost:user:7:20260927", "corrupt")
    worker = GenerationCostWorker(client)
    assert await worker.run(spec.attempt_id) == "needs_review"
    assert not client.exists("cost:global:20260927")
    assert await worker.run(spec.attempt_id) == "not_claimed"


@pytest.mark.asyncio
async def test_unknown_generation_never_becomes_billable(attempt):
    client, store, spec = attempt
    token = store.start(spec)
    store.mark_unknown(spec, token)
    assert await GenerationCostWorker(client).run(spec.attempt_id) == "not_claimed"
    assert not list(client.scan_iter("cost:*"))


@pytest.mark.asyncio
async def test_cancelled_worker_keeps_lease_until_target_thread_finishes(attempt):
    client, store, spec = completed(attempt)
    entered, release, ended = threading.Event(), threading.Event(), threading.Event()
    real = EffectWriter(client)

    def slow(*args, **kwargs):
        entered.set()
        try:
            if not release.wait(5):
                raise TimeoutError("test release missing")
            return real.consume_cost(*args, **kwargs)
        finally:
            ended.set()

    task = asyncio.create_task(GenerationCostWorker(client,
        writer=SimpleNamespace(consume_cost=slow)).run(spec.attempt_id))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await GenerationCostWorker(client).run(spec.attempt_id) == "not_claimed"
    finally:
        release.set()
        assert await asyncio.to_thread(ended.wait, 3)
    expire(client, store, spec, "cost_lease_until_ms")
    assert await GenerationCostWorker(client).run(spec.attempt_id) == "already_applied"
    assert float(client.get("cost:global:20260927")) == pytest.approx(.05)
