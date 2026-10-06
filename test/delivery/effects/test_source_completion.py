"""Permanent source receipts survive later business changes and lost responses."""
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace

import pytest

from src.services.persistence.effects import EffectConflict, EffectNeedsReview, EffectUnavailable
from src.services.persistence.effects.source import SourceEffectWriter, source_effect_id
from src.services.persistence.reminder_state import INTENT_KEY
from test.autonomy.test_pending_atomic import isolated_redis
from test.delivery.effects.source_fixtures import install_task, make_source, replace_source


@pytest.fixture(params=["followup", "reminder"])
def source_case(isolated_redis, request):
    client = isolated_redis
    repo, snapshot, spec = make_source(client, request.param)
    install_task(client, spec)
    return client, repo, snapshot, spec


def test_source_write_response_lost_then_source_recreated_retains_receipt(source_case):
    client, repo, snapshot, spec = source_case
    effect_id = source_effect_id(spec)

    def lose_response(*args):
        client.eval(*args)
        raise ConnectionError("synthetic lost response")

    with pytest.raises(EffectUnavailable):
        SourceEffectWriter(SimpleNamespace(eval=lose_response)).complete_effect(effect_id, spec)
    if spec.kind == "followup":
        body = json.loads(client.hget(spec.source_key, spec.source_field))
        assert body["status"] == "done"
        assert client.zscore("relationship:followups", f"7:{spec.business_id}") is None
        replace_source(repo, snapshot, spec)
    else:
        assert repo.load(spec.business_id) is None
        assert json.loads(client.hget(INTENT_KEY, spec.business_id))["reason"] == "complete"
        assert repo.create(snapshot.record.model_copy(update={"content": "replacement"}), bot_id="99").ok
    replaced_raw = client.hget(spec.source_key, spec.source_field)
    writer = SourceEffectWriter(client)
    assert writer.complete_effect(effect_id, spec) == "already_applied"
    assert client.hget(spec.source_key, spec.source_field) == replaced_raw
    # Once business state disappears, the independent receipt is still enough.
    client.hdel(spec.source_key, spec.source_field)
    client.hdel(spec.revision_key, spec.source_field)
    assert writer.complete_effect(effect_id, spec) == "already_applied"
    receipt_key = "mako:delivery:v1:effect-source:" + effect_id
    assert client.ttl(receipt_key) == -1
    with pytest.raises(EffectConflict):
        writer.complete_effect(effect_id, replace(spec, payload="conflicting body"))


def test_new_revision_is_skipped_with_stable_receipt(source_case):
    client, repo, snapshot, spec = source_case
    replace_source(repo, snapshot, spec)
    before = client.hget(spec.source_key, spec.source_field)
    writer = SourceEffectWriter(client)
    effect_id = source_effect_id(spec)
    assert writer.complete_effect(effect_id, spec) == "superseded"
    assert client.hget(spec.source_key, spec.source_field) == before
    client.hdel(spec.source_key, spec.source_field)
    assert writer.complete_effect(effect_id, spec) == "superseded"


def test_missing_source_without_evidence_is_not_success(source_case):
    client, _, _, spec = source_case
    client.hdel(spec.source_key, spec.source_field)
    if spec.kind == "reminder":
        client.hdel(INTENT_KEY, spec.source_field)
    effect_id = source_effect_id(spec)
    assert SourceEffectWriter(client).complete_effect(effect_id, spec) == "missing"
    assert not client.exists("mako:delivery:v1:effect-source:" + effect_id)


def test_same_revision_changed_body_is_not_completed(source_case):
    client, _, _, spec = source_case
    body = json.loads(client.hget(spec.source_key, spec.source_field))
    body["content"] = "changed without revision"
    raw = json.dumps(body)
    client.hset(spec.source_key, spec.source_field, raw)
    effect_id = source_effect_id(spec)
    assert SourceEffectWriter(client).complete_effect(effect_id, spec) == "inconsistent"
    assert client.hget(spec.source_key, spec.source_field) == raw
    assert not client.exists("mako:delivery:v1:effect-source:" + effect_id)


def test_concurrent_source_completion_applies_once(source_case):
    client, _, _, spec = source_case
    writer = SourceEffectWriter(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: writer.complete_effect(source_effect_id(spec), spec), range(2)))
    assert sorted(results) == ["already_applied", "applied"]


@pytest.mark.parametrize("fault", ["unknown", "missing_task", "digest", "duplicate", "review"])
def test_untrusted_action_or_task_cannot_complete_source(source_case, fault):
    client, _, _, spec = source_case
    key = "mako:delivery:v1:" + spec.action_id
    action = json.loads(client.get(key))
    if fault == "unknown":
        action["state"] = "unknown"
    elif fault == "missing_task":
        action.pop("effects")
    elif fault == "digest":
        action["effects"][0]["payload_digest"] = "0" * 40
    elif fault == "duplicate":
        action["effects"].append(action["effects"][0].copy())
    else:
        action["effects"][0]["state"] = "needs_review"
    client.set(key, json.dumps(action))
    before = client.hget(spec.source_key, spec.source_field)
    effect_id = source_effect_id(spec)
    assert SourceEffectWriter(client).complete_effect(effect_id, spec) == "wrong_action"
    assert client.hget(spec.source_key, spec.source_field) == before
    assert not client.exists("mako:delivery:v1:effect-source:" + effect_id)


def test_explicit_reminder_cancel_is_distinct_from_missing(isolated_redis):
    client = isolated_redis
    repo, snapshot, spec = make_source(client, "reminder")
    install_task(client, spec)
    assert repo.cancel(snapshot).ok
    effect_id = source_effect_id(spec)
    writer = SourceEffectWriter(client)
    assert writer.complete_effect(effect_id, spec) == "cancelled"
    assert repo.create(snapshot.record, bot_id="99").ok
    current = repo.load(spec.business_id)
    assert writer.complete_effect(effect_id, spec) == "cancelled"
    assert repo.load(spec.business_id) == current


@pytest.mark.parametrize("kind", ["followup", "reminder"])
def test_owner_unknown_time_allows_only_explicit_source_task(isolated_redis, kind):
    client = isolated_redis
    _, _, spec = make_source(client, kind)
    key = install_task(client, spec, owner=True)
    before = client.get(key)
    assert SourceEffectWriter(client).complete_effect(source_effect_id(spec), spec) == "applied"
    assert client.get(key) == before
    assert json.loads(before)["delivered_at_ms"] is None


def test_bad_due_index_type_prevents_partial_source_write(isolated_redis):
    client = isolated_redis
    _, _, spec = make_source(client, "followup")
    install_task(client, spec)
    client.delete("relationship:followups")
    client.set("relationship:followups", "wrong type")
    before = client.hget(spec.source_key, spec.source_field)
    with pytest.raises(EffectNeedsReview):
        SourceEffectWriter(client).complete_effect(source_effect_id(spec), spec)
    assert client.hget(spec.source_key, spec.source_field) == before
