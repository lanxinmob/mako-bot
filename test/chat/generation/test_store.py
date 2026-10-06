"""One-shot model admission and frozen results under Redis response loss."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from src.services.persistence.effects import EffectConflict, EffectNeedsReview, EffectUnavailable
from src.services.persistence.generation.models import GenerationSpec
from src.services.persistence.generation.store import GenerationStore
from test.autonomy.test_pending_atomic import isolated_redis


@pytest.fixture
def attempt(isolated_redis):
    spec = GenerationSpec("a" * 64, 7, "reply", "test-model", "b" * 64,
                          "20260927", .001, .002, .03)
    return isolated_redis, GenerationStore(isolated_redis), spec


def test_concurrent_creation_grants_one_token_and_never_reacquires(attempt):
    client, store, spec = attempt
    with ThreadPoolExecutor(max_workers=2) as pool:
        tokens = list(pool.map(lambda _: store.start(spec), range(2)))
    assert sum(token is not None for token in tokens) == 1
    token = next(token for token in tokens if token)
    before = client.get(store.key(spec.attempt_id))
    assert store.start(replace(spec, model="changed-model")) is None
    assert client.get(store.key(spec.attempt_id)) == before
    assert store.mark_unknown(spec, token) == "unknown"
    assert store.start(spec) is None
    assert client.ttl(store.key(spec.attempt_id)) == -1


def test_start_response_loss_does_not_return_permission(attempt):
    client, store, spec = attempt

    def lost(*args):
        client.eval(*args)
        raise ConnectionError("synthetic response loss")

    with pytest.raises(EffectUnavailable):
        GenerationStore(SimpleNamespace(eval=lost)).start(spec)
    assert store.start(spec) is None
    assert json.loads(client.get(store.key(spec.attempt_id)))["state"] == "calling"


def test_late_completion_keeps_original_date_and_freezes_amount(attempt):
    client, store, spec = attempt
    token = store.start(spec)
    store.mark_unknown(spec, token)
    assert store.complete(spec, token, .05) == "completed"
    first = client.get(store.key(spec.attempt_id))
    assert store.complete(spec, token, .05) == "completed"
    assert store.mark_unknown(spec, token) == "completed"
    assert client.get(store.key(spec.attempt_id)) == first
    value = json.loads(first)
    assert value["cost_state"] == "pending"
    assert json.loads(value["spec_json"])["cost_day"] == "20260927"
    for changed_spec, changed_token, changed_amount in [
        (replace(spec, cost_day="20260928"), token, .05),
        (spec, "f" * 64, .05), (spec, token, .06),
    ]:
        with pytest.raises(EffectConflict):
            store.complete(changed_spec, changed_token, changed_amount)
    assert client.get(store.key(spec.attempt_id)) == first


def test_completion_response_loss_is_idempotent_without_cost_increment(attempt):
    client, store, spec = attempt
    token = store.start(spec)

    def lost(*args):
        client.eval(*args)
        raise TimeoutError("synthetic response loss")

    with pytest.raises(EffectUnavailable):
        GenerationStore(SimpleNamespace(eval=lost)).complete(spec, token, .04)
    assert store.complete(spec, token, .04) == "completed"
    assert not list(client.scan_iter("cost:*"))


def test_zero_cost_and_missing_evidence_do_not_create_charge(attempt):
    client, store, spec = attempt
    assert store.complete(spec, "f" * 64, 0) == "missing"
    assert not client.exists(store.key(spec.attempt_id))
    token = store.start(spec)
    store.complete(spec, token, 0)
    assert json.loads(client.get(store.key(spec.attempt_id)))["cost_state"] == "complete"


@pytest.mark.parametrize("amount", [-1, float("inf"), float("nan"), True, "0.1"])
def test_invalid_amount_cannot_mutate_attempt(attempt, amount):
    client, store, spec = attempt
    token = store.start(spec)
    first = client.dump(store.key(spec.attempt_id))
    with pytest.raises(ValueError):
        store.complete(spec, token, amount)
    assert client.dump(store.key(spec.attempt_id)) == first


def test_unavailable_or_unexpected_response_grants_no_token(attempt):
    _, _, spec = attempt
    with pytest.raises(EffectUnavailable):
        GenerationStore(None).start(spec)
    with pytest.raises(EffectNeedsReview):
        GenerationStore(SimpleNamespace(eval=lambda *args: [])).start(spec)
