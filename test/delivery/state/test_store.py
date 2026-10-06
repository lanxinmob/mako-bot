import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from unittest.mock import AsyncMock, Mock

import pytest

from src.services.delivery.state import DeliveryAttempt, DeliverySpec, DeliveryStore, DeliveryUnavailable
from test.autonomy.test_pending_atomic import isolated_redis


@pytest.fixture
def delivery(isolated_redis):
    seconds, micros = isolated_redis.time()
    spec = DeliverySpec("followup", "99", "private", "7", "memory-a", "revision-1",
                        "synthetic payload", seconds * 1000 + micros // 1000 + 60000)
    return isolated_redis, DeliveryStore(isolated_redis), spec


def expire(client, store, spec):
    key = store.key(spec.action_id)
    state = json.loads(client.get(key))
    state["lease_until_ms"] = 0
    client.set(key, json.dumps(state))


def test_competing_clients_only_one_claims_and_payload_is_frozen(delivery):
    client, store, spec = delivery
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: DeliveryStore(client).claim(spec), range(2)))
    assert sum(result.ok for result in results) == 1
    assert all(result.token == "" for result in results if not result.ok)
    changed = replace(spec, payload="different random content")
    assert changed.action_id == spec.action_id
    assert store.claim(changed).code == "changed"
    inspected = store.inspect(spec.action_id)
    assert inspected.token == "" and inspected.spec == spec
    assert client.ttl(store.key(spec.action_id)) == -1


def test_queue_recovery_fences_old_token_but_sending_never_reclaims(delivery):
    client, store, spec = delivery
    first = store.claim(spec)
    expire(client, store, spec)
    second = store.claim(spec)
    assert second.ok and first.token != second.token
    assert not store.begin_send(spec, first.token).ok
    assert not store.cancel(spec.action_id, first.token).ok
    assert store.begin_send(spec, second.token).ok
    assert not store.begin_send(spec, second.token).ok
    expire(client, store, spec)
    assert store.inspect(spec.action_id).state == "unknown"
    assert not store.claim(spec).ok
    # A late positive acknowledgement can record truth without sending again.
    assert store.mark_sent(spec.action_id, second.token).ok
    assert not store.mark_unknown(spec.action_id, second.token).ok


def test_cancel_reject_and_expiry_do_not_authorize_old_work(delivery):
    _, store, spec = delivery
    claim = store.claim(spec)
    assert store.reject_before_send(spec.action_id, claim.token).ok
    replacement = store.claim(spec)
    assert replacement.ok and replacement.token != claim.token
    assert store.cancel(spec.action_id, replacement.token).ok
    assert not store.begin_send(spec, replacement.token).ok
    assert not store.claim(spec).ok
    expired = replace(spec, business_id="expired", valid_until_ms=1)
    assert store.claim(expired).code == "expired"
    assert store.inspect(expired.action_id).code == "missing"


@pytest.mark.parametrize("client", [None, Mock(eval=Mock(side_effect=ConnectionError))])
def test_redis_failure_is_closed(client):
    spec = DeliverySpec("digest", "99", "group", "1", "date", "1", "body", 2**52)
    with pytest.raises(DeliveryUnavailable):
        DeliveryStore(client).claim(spec)


@pytest.mark.asyncio
async def test_one_attempt_records_ack_without_repeating_callback(delivery):
    client, store, spec = delivery
    claim = store.claim(spec)
    attempt = DeliveryAttempt(store, spec, claim.token)
    callback = AsyncMock(return_value=True)
    assert await attempt.send(callback)
    assert not await attempt.send(callback)
    callback.assert_awaited_once_with(spec)
    assert attempt.acknowledged and attempt.state_confirmed
    assert store.inspect(spec.action_id).state == "sent"
    assert json.loads(client.get(store.key(spec.action_id)))["effects_state"] == "pending"


@pytest.mark.asyncio
async def test_lost_begin_response_prevents_transport_and_future_claim(delivery, monkeypatch):
    _, store, spec = delivery
    claim = store.claim(spec)
    original = store.begin_send

    def lost_response(*args):
        assert original(*args).ok
        raise DeliveryUnavailable("response lost")

    monkeypatch.setattr(store, "begin_send", lost_response)
    callback = AsyncMock(return_value=True)
    with pytest.raises(DeliveryUnavailable):
        await DeliveryAttempt(store, spec, claim.token).send(callback)
    callback.assert_not_awaited()
    assert store.inspect(spec.action_id).state == "unknown"
    assert not store.claim(spec).ok


@pytest.mark.asyncio
async def test_cancellation_after_transport_entry_keeps_unknown(delivery):
    _, store, spec = delivery
    claim = store.claim(spec)
    entered = asyncio.Event()

    async def callback(_spec):
        entered.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(DeliveryAttempt(store, spec, claim.token).send(callback))
    await asyncio.wait_for(entered.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert store.inspect(spec.action_id).state == "unknown"
    assert not store.claim(spec).ok


@pytest.mark.asyncio
async def test_lost_sent_response_does_not_negate_ack_or_resend(delivery, monkeypatch):
    _, store, spec = delivery
    claim = store.claim(spec)
    mark_sent = store.mark_sent

    def lost_response(*args):
        assert mark_sent(*args).ok
        raise DeliveryUnavailable("response lost")

    monkeypatch.setattr(store, "mark_sent", lost_response)
    attempt = DeliveryAttempt(store, spec, claim.token)
    callback = AsyncMock(return_value=True)
    assert await attempt.send(callback)
    assert attempt.acknowledged and not attempt.state_confirmed
    assert store.inspect(spec.action_id).state == "sent"
    assert not store.claim(spec).ok
    callback.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancelled_begin_thread_cannot_start_after_unknown_is_recorded(delivery, monkeypatch):
    _, store, spec = delivery
    claim = store.claim(spec)
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = store.begin_send
    results = []

    def delayed_begin(*args):
        entered.set()
        try:
            if not release.wait(3):
                raise AssertionError("test did not release begin thread")
            result = original(*args)
            results.append(result)
            return result
        finally:
            finished.set()

    monkeypatch.setattr(store, "begin_send", delayed_begin)
    callback = AsyncMock(return_value=True)
    task = asyncio.create_task(DeliveryAttempt(store, spec, claim.token).send(callback))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert store.inspect(spec.action_id).state == "unknown"
    finally:
        release.set()
        assert await asyncio.to_thread(finished.wait, 2)
    assert len(results) == 1 and not results[0].ok
    callback.assert_not_awaited()
