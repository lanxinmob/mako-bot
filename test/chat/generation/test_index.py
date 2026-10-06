"""Cost discovery preserves authority through partial writes and stale repair."""
import json

import pytest

from src.services.persistence.effects import EffectUnavailable
from src.services.persistence.generation.costs import GenerationCosts
from src.services.persistence.generation.index import GenerationCostIndex
from src.services.persistence.generation.index_scripts import COST_DUE_KEY
from test.autonomy.test_pending_atomic import isolated_redis
from test.chat.generation.test_store import attempt


def test_index_tracks_pending_lease_retry_and_terminal(attempt):
    client, store, spec = attempt
    index, costs = GenerationCostIndex(client), GenerationCosts(client)
    store.complete(spec, store.start(spec), .02)
    assert index.due_ids() == [spec.attempt_id]
    lease = costs.claim(spec.attempt_id)
    assert index.due_ids() == []
    assert costs.finish(lease, "unavailable")
    state = json.loads(client.get(store.key(spec.attempt_id)))
    assert client.zscore(COST_DUE_KEY, spec.attempt_id) == state["cost_next_attempt_at_ms"]
    state["cost_next_attempt_at_ms"] = 0
    client.set(store.key(spec.attempt_id), json.dumps(state))
    index.repair(spec.attempt_id, client.get(store.key(spec.attempt_id)))
    renewed = costs.claim(spec.attempt_id)
    assert renewed is not None
    assert costs.finish(renewed, "applied")
    assert client.zscore(COST_DUE_KEY, spec.attempt_id) is None
    assert client.ttl(store.key(spec.attempt_id)) == -1


def test_broken_index_does_not_erase_completed_model_evidence(attempt):
    client, store, spec = attempt
    token = store.start(spec)
    client.set(COST_DUE_KEY, "wrong type")
    with pytest.raises(EffectUnavailable):
        store.complete(spec, token, .02)
    raw = client.get(store.key(spec.attempt_id))
    assert json.loads(raw)["state"] == "completed"
    # Delete only this test's corrupt discovery index, never the source evidence.
    client.delete(COST_DUE_KEY)
    index = GenerationCostIndex(client)
    assert index.repair(spec.attempt_id, raw) == "repaired"
    assert index.due_ids() == [spec.attempt_id]
    assert client.get(store.key(spec.attempt_id)) == raw


def test_stale_repair_and_finish_cannot_overwrite_new_lease(attempt):
    client, store, spec = attempt
    store.complete(spec, store.start(spec), .02)
    index, costs = GenerationCostIndex(client), GenerationCosts(client)
    old_raw = client.get(store.key(spec.attempt_id))
    old = costs.claim(spec.attempt_id)
    state = json.loads(client.get(store.key(spec.attempt_id)))
    state["cost_lease_until_ms"] = 0
    client.set(store.key(spec.attempt_id), json.dumps(state))
    current = costs.claim(spec.attempt_id)
    score = client.zscore(COST_DUE_KEY, spec.attempt_id)
    assert index.repair(spec.attempt_id, old_raw) == "changed"
    assert not costs.finish(old, "applied")
    assert client.zscore(COST_DUE_KEY, spec.attempt_id) == score
    assert costs.inspect(spec.attempt_id).token == current.token


def test_invalid_and_missing_members_leave_authority_untouched(attempt):
    client, store, spec = attempt
    key = store.key(spec.attempt_id)
    client.set(key, "broken evidence")
    client.zadd(COST_DUE_KEY, {spec.attempt_id: 0, "invalid-id": 0})
    index = GenerationCostIndex(client)
    assert index.repair(spec.attempt_id, client.get(key)) == "removed_invalid"
    assert index.repair("invalid-id", None) == "removed_missing"
    assert client.get(key) == "broken evidence"
    assert index.due_ids() == []


def test_invalid_utf8_member_does_not_hide_valid_pending(attempt):
    client, store, spec = attempt
    store.complete(spec, store.start(spec), .02)
    client.zadd(COST_DUE_KEY, {b"\xff": 0})
    index = GenerationCostIndex(client)
    assert index.due_ids() == [b"\xff", spec.attempt_id]
    assert index.repair(b"\xff", None) == "removed_missing"
    assert index.due_ids() == [spec.attempt_id]
    assert GenerationCosts(client).inspect(spec.attempt_id).state == "pending"


def test_expiring_evidence_is_removed_from_index_without_changing_record(attempt):
    client, store, spec = attempt
    store.complete(spec, store.start(spec), .02)
    key = store.key(spec.attempt_id)
    raw = client.get(key)
    client.pexpire(key, 60000)
    before = client.pttl(key)
    index = GenerationCostIndex(client)
    assert index.repair(spec.attempt_id, raw) == "removed_invalid"
    assert client.get(key) == raw
    assert 0 < client.pttl(key) <= before
    assert index.due_ids() == []
    # Once an operator restores permanence, a fresh snapshot may rebuild it.
    client.persist(key)
    assert index.repair(spec.attempt_id, client.get(key)) == "repaired"
    assert index.due_ids() == [spec.attempt_id]


def test_wrong_type_repair_preserves_source_and_new_string_replacement(attempt):
    from src.services.persistence.generation.index_scripts import REMOVE_WRONG_TYPE
    client, store, spec = attempt
    key = store.key(spec.attempt_id)
    client.hset(key, "original", "evidence")
    client.zadd(COST_DUE_KEY, {spec.attempt_id: 0})
    before = client.dump(key)
    assert GenerationCostIndex(client).repair_current(spec.attempt_id) == "removed_invalid"
    assert client.dump(key) == before
    # A delayed quarantine after source replacement cannot remove its new work.
    client.delete(key)
    store.complete(spec, store.start(spec), .02)
    score = client.zscore(COST_DUE_KEY, spec.attempt_id)
    assert client.eval(REMOVE_WRONG_TYPE, 2, key, COST_DUE_KEY, spec.attempt_id, "hash") == "changed"
    assert client.zscore(COST_DUE_KEY, spec.attempt_id) == score


def test_current_repair_reads_invalid_utf8_evidence_without_decoding_failure(attempt):
    client, store, spec = attempt
    key = store.key(spec.attempt_id)
    client.set(key, b"\xff")
    before = client.dump(key)
    client.zadd(COST_DUE_KEY, {spec.attempt_id: 0})
    assert GenerationCostIndex(client).repair_current(spec.attempt_id) == "removed_invalid"
    assert client.dump(key) == before
    assert client.zscore(COST_DUE_KEY, spec.attempt_id) is None


@pytest.mark.parametrize("state,missing", [
    ("leased", "cost_lease_until_ms"),
    ("retry_wait", "cost_next_attempt_at_ms"),
])
def test_missing_required_deadline_cannot_block_index_repair(attempt, state, missing):
    client, store, spec = attempt
    store.complete(spec, store.start(spec), .02)
    costs = GenerationCosts(client)
    lease = costs.claim(spec.attempt_id)
    if state == "retry_wait":
        assert costs.finish(lease, "unavailable")
    key = store.key(spec.attempt_id)
    record = json.loads(client.get(key))
    del record[missing]
    client.set(key, json.dumps(record))
    before = client.dump(key)
    client.zadd(COST_DUE_KEY, {spec.attempt_id: 0})
    assert GenerationCostIndex(client).repair_current(spec.attempt_id) == "removed_invalid"
    assert client.dump(key) == before
    assert client.zscore(COST_DUE_KEY, spec.attempt_id) is None
    assert not list(client.scan_iter("cost:*"))


@pytest.mark.asyncio
async def test_repair_classifies_old_call_without_reinvocation_and_accepts_late_result(attempt):
    from src.services.chat.generation.discovery import GenerationCostScanner
    client, store, spec = attempt
    token = store.start(spec)
    key = store.key(spec.attempt_id)
    index = GenerationCostIndex(client)
    fresh = client.get(key)
    assert index.repair_current(spec.attempt_id) == "repaired"
    assert client.get(key) == fresh
    record = json.loads(fresh)
    seconds, micros = client.time()
    record["started_at_ms"] = seconds * 1000 + micros // 1000 - 300001
    client.set(key, json.dumps(record))
    stale = client.get(key)
    scanner, cursor = GenerationCostScanner(client), "0:0"
    for _ in range(20):
        page = await scanner.repair_page(cursor)
        if page.next_cursor is None:
            break
        cursor = page.next_cursor
    else:
        pytest.fail("isolated history scan did not finish")
    classified = json.loads(client.get(key))
    assert classified == {**record, "state": "unknown", "cost_state": "needs_review"}
    assert store.start(spec) is None
    assert index.due_ids() == []
    assert not list(client.scan_iter("cost:*"))
    assert store.complete(spec, token, .02) == "completed"
    completed = client.get(key)
    assert index.repair(spec.attempt_id, stale) == "changed"
    assert client.get(key) == completed
    assert index.due_ids() == [spec.attempt_id]
