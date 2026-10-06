from concurrent.futures import ThreadPoolExecutor
import json
from types import SimpleNamespace

import pytest

from src.services.persistence.effects import EffectNeedsReview, EffectUnavailable
from src.services.persistence.history_commit.tasks import HistoryEffects
from test.autonomy.test_pending_atomic import isolated_redis
from test.persistence.history_commit.test_delivery import planned


@pytest.fixture
def acknowledged(planned):
    client, delivery, plan = planned
    token = delivery.create(plan)
    assert delivery.transition(plan.action_id, token, "begin") == "sending"
    assert delivery.transition(plan.action_id, token, "sent", delivered_at_ms=1791240000123) == "sent"
    return client, delivery, plan, HistoryEffects(client)


def make_due(client, delivery, plan, kind, field):
    key = delivery.key(plan.action_id)
    data = json.loads(client.get(key))
    seconds, micros = client.time()
    data["task_meta"][kind][field] = seconds * 1000 + micros // 1000 - 1
    client.set(key, json.dumps(data))


def test_each_task_has_one_independent_concurrent_lease(acknowledged):
    client, delivery, plan, store = acknowledged
    with ThreadPoolExecutor(2) as pool:
        claims = list(pool.map(lambda _: store.claim(plan.action_id, "session"), range(2)))
    leases = [lease for lease in claims if lease is not None]
    assert len(leases) == 1
    global_lease = store.claim(plan.action_id, "global")
    assert global_lease.task.token != leases[0].task.token
    assert store.finish(leases[0], "history_conflict")
    assert store.finish(global_lease, "applied")
    snapshot = store.inspect(plan.action_id)
    assert {t.kind: t.state for t in snapshot.tasks} == {"session": "needs_review", "global": "complete"}
    assert store.finish(global_lease, "applied")
    assert store.claim(plan.action_id, "session") is None
    assert client.ttl(delivery.key(plan.action_id)) == -1


def test_expired_lease_rotates_token_and_rejects_old_settlement(acknowledged):
    client, delivery, plan, store = acknowledged
    old = store.claim(plan.action_id, "session")
    make_due(client, delivery, plan, "session", "lease_until_ms")
    fresh = store.claim(plan.action_id, "session")
    assert fresh.task.token != old.task.token and fresh.task.attempts == 2
    assert fresh.plan == old.plan and fresh.delivered_at_ms == old.delivered_at_ms
    assert not store.finish(old, "applied")
    assert store.finish(fresh, "already_applied")


def test_lost_claim_response_does_not_regrant_unexpired_lease(acknowledged):
    client, delivery, plan, store = acknowledged

    def lost(*args):
        client.eval(*args)
        raise ConnectionError("synthetic lease response loss")

    broken = HistoryEffects(SimpleNamespace(get=client.get, eval=lost))
    with pytest.raises(EffectUnavailable):
        broken.claim(plan.action_id, "session")
    assert store.claim(plan.action_id, "session") is None
    assert next(t for t in store.inspect(plan.action_id).tasks if t.kind == "session").state == "leased"
    make_due(client, delivery, plan, "session", "lease_until_ms")
    assert store.claim(plan.action_id, "session").task.attempts == 2


def test_unknown_and_volatile_sent_records_never_grant_history(planned):
    client, delivery, plan = planned
    token = delivery.create(plan)
    delivery.transition(plan.action_id, token, "begin")
    delivery.transition(plan.action_id, token, "unknown")
    store = HistoryEffects(client)
    assert store.claim(plan.action_id, "session") is None
    assert store.claim(plan.action_id, "global") is None
    delivery.transition(plan.action_id, token, "sent", delivered_at_ms=1791240000123)
    key = delivery.key(plan.action_id)
    client.pexpire(key, 60000)
    before = client.dump(key)
    with pytest.raises(EffectNeedsReview):
        store.claim(plan.action_id, "global")
    assert client.dump(key) == before and client.pttl(key) > 0


def test_missing_or_inconsistent_deadline_is_review_without_mutation(acknowledged):
    client, delivery, plan, store = acknowledged
    store.claim(plan.action_id, "global")
    key = delivery.key(plan.action_id)
    original = json.loads(client.get(key))
    for field in ("lease_until_ms", "token", "attempts"):
        data = json.loads(json.dumps(original))
        del data["task_meta"]["global"][field]
        client.set(key, json.dumps(data))
        before = client.dump(key)
        with pytest.raises(EffectNeedsReview):
            store.claim(plan.action_id, "global")
        assert client.dump(key) == before


def test_retry_wait_is_not_due_and_old_token_cannot_finish_new_lease(acknowledged):
    client, delivery, plan, store = acknowledged
    lease = store.claim(plan.action_id, "global")
    assert store.defer(lease) and store.defer(lease)
    task = next(t for t in store.inspect(plan.action_id).tasks if t.kind == "global")
    assert task.state == "retry_wait" and task.result == "unavailable"
    assert store.claim(plan.action_id, "global") is None
    make_due(client, delivery, plan, "global", "next_attempt_at_ms")
    fresh = store.claim(plan.action_id, "global")
    assert fresh.task.attempts == 2
    assert not store.finish(lease, "applied")
    assert store.finish(fresh, "already_applied")
