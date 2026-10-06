"""Real Redis lease races and response-loss checks, without message transport."""
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from src.services.delivery.effects.store import EffectStore
from src.services.delivery.state import DeliveryStore
from src.services.persistence.effects import EffectNeedsReview, EffectUnavailable
from test.autonomy.test_pending_atomic import isolated_redis
from test.delivery.effects.test_plan_activation import planned


def activate(client, *, kind="periodic", owner=False):
    spec, plan = planned(client, kind)
    delivery = DeliveryStore(client, require_effects=True)
    claimed = delivery.claim(spec, plan=plan)
    if owner:
        delivery.mark_unknown(spec.action_id, claimed.token)
        assert delivery.reconcile(spec.action_id, delivered=True, operator_id="99").ok
    else:
        assert delivery.begin_send(spec, claimed.token).ok
        assert delivery.mark_sent(spec.action_id, claimed.token).ok
    return spec, EffectStore(client)


def rewrite_task(client, spec, effect_id, **values):
    key = DeliveryStore.key(spec.action_id)
    action = json.loads(client.get(key))
    next(task for task in action["effects"] if task["effect_id"] == effect_id).update(values)
    client.set(key, json.dumps(action))


def test_two_workers_cannot_hold_same_live_lease(isolated_redis):
    spec, store = activate(isolated_redis)
    task = store.inspect(spec.action_id).tasks[0]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: store.claim(spec.action_id, task.effect_id), range(2)))
    assert sum(item is not None for item in results) == 1
    lease = next(item for item in results if item is not None)
    assert lease.task.lease_token != json.loads(isolated_redis.get(DeliveryStore.key(spec.action_id)))["token"]
    assert lease.task.payload_json == task.payload_json


def test_expired_worker_cannot_finish_or_defer_new_lease(isolated_redis):
    spec, store = activate(isolated_redis, kind="reminder")
    task = store.inspect(spec.action_id).tasks[0]
    old = store.claim(spec.action_id, task.effect_id)
    rewrite_task(isolated_redis, spec, task.effect_id, lease_until_ms=0)
    current = store.claim(spec.action_id, task.effect_id)
    assert current.task.attempts == 2 and current.task.lease_token != old.task.lease_token
    before = isolated_redis.get(DeliveryStore.key(spec.action_id))
    assert not store.finish(old, "applied") and not store.defer(old)
    assert isolated_redis.get(DeliveryStore.key(spec.action_id)) == before
    assert store.finish(current, "superseded")
    action = json.loads(isolated_redis.get(DeliveryStore.key(spec.action_id)))
    assert action["effects_state"] == "complete_with_skips"
    assert action["state"] == "sent"


def test_retry_backoff_and_duplicate_defer_do_not_extend_each_other(isolated_redis):
    spec, store = activate(isolated_redis, kind="reminder")
    task = store.inspect(spec.action_id).tasks[0]
    lease = store.claim(spec.action_id, task.effect_id)
    assert store.defer(lease)
    first = isolated_redis.get(DeliveryStore.key(spec.action_id))
    assert store.defer(lease)
    assert isolated_redis.get(DeliveryStore.key(spec.action_id)) == first
    assert store.claim(spec.action_id, task.effect_id) is None
    rewrite_task(isolated_redis, spec, task.effect_id, next_attempt_at_ms=0)
    retried = store.claim(spec.action_id, task.effect_id)
    assert retried.task.attempts == 2 and retried.task.payload_json == lease.task.payload_json


@pytest.mark.parametrize("operation", ["claim", "finish", "defer"])
def test_lost_lease_transition_response_keeps_committed_state(isolated_redis, operation):
    client = isolated_redis
    spec, store = activate(client, kind="reminder")
    task = store.inspect(spec.action_id).tasks[0]
    lease = store.claim(spec.action_id, task.effect_id) if operation != "claim" else None

    def lost(*args):
        client.eval(*args)
        raise ConnectionError("synthetic lost result")

    uncertain = EffectStore(SimpleNamespace(get=client.get, eval=lost))
    with pytest.raises(EffectUnavailable):
        if operation == "claim":
            uncertain.claim(spec.action_id, task.effect_id)
        elif operation == "finish":
            uncertain.finish(lease, "applied")
        else:
            uncertain.defer(lease)
    first = client.get(DeliveryStore.key(spec.action_id))
    if operation == "claim":
        assert store.claim(spec.action_id, task.effect_id) is None
    elif operation == "finish":
        assert store.finish(lease, "applied")
    else:
        assert store.defer(lease)
    assert client.get(DeliveryStore.key(spec.action_id)) == first


def test_owner_time_review_does_not_block_source_completion_task(isolated_redis):
    spec, store = activate(isolated_redis, kind="followup", owner=True)
    source, timed = store.inspect(spec.action_id).tasks
    assert store.claim(spec.action_id, timed.effect_id) is None
    lease = store.claim(spec.action_id, source.effect_id)
    assert lease is not None and store.finish(lease, "applied")
    action = json.loads(isolated_redis.get(DeliveryStore.key(spec.action_id)))
    assert action["effects_state"] == "needs_review" and action["delivered_at_ms"] is None
    assert action["effects"][1]["state"] == "needs_review"


def test_invalid_payload_does_not_receive_a_lease(isolated_redis):
    spec, store = activate(isolated_redis)
    task = store.inspect(spec.action_id).tasks[0]
    rewrite_task(isolated_redis, spec, task.effect_id, payload_json="{}")
    first = isolated_redis.get(DeliveryStore.key(spec.action_id))
    with pytest.raises(EffectNeedsReview):
        store.claim(spec.action_id, task.effect_id)
    assert isolated_redis.get(DeliveryStore.key(spec.action_id)) == first


def test_other_task_race_cannot_be_overwritten_by_validated_stale_snapshot(isolated_redis):
    client = isolated_redis
    spec, store = activate(client)
    first, second, _ = store.inspect(spec.action_id).tasks

    def interleave(*args):
        assert store.claim(spec.action_id, second.effect_id) is not None
        return client.eval(*args)

    racing = EffectStore(SimpleNamespace(get=client.get, eval=interleave))
    assert racing.claim(spec.action_id, first.effect_id) is None
    current = store.inspect(spec.action_id)
    assert current.tasks[0].state == "pending" and current.tasks[1].state == "leased"


def test_unknown_and_legacy_sent_never_infer_tasks(isolated_redis):
    client = isolated_redis
    spec, _ = planned(client, "reminder")
    delivery = DeliveryStore(client)
    claim = delivery.claim(spec)
    delivery.mark_unknown(spec.action_id, claim.token)
    store = EffectStore(client)
    assert store.inspect(spec.action_id) is None
    delivery.reconcile(spec.action_id, delivered=True, operator_id="99")
    first = client.get(delivery.key(spec.action_id))
    with pytest.raises(EffectNeedsReview):
        store.inspect(spec.action_id)
    assert client.get(delivery.key(spec.action_id)) == first
