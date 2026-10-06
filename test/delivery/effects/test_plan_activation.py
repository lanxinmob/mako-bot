"""Sent and its complete effect plan become visible in the same action write."""
import hashlib
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from src.services.delivery.effects.plans import EffectPlan, build_plan
from src.services.delivery.state import DeliverySpec, DeliveryStore, DeliveryUnavailable
from src.services.persistence.effects.source import SourceEffectWriter, source_effect_id
from test.autonomy.test_pending_atomic import isolated_redis
from test.delivery.effects.source_fixtures import make_source


def planned(client, kind):
    if kind == "periodic":
        spec = DeliverySpec("periodic", "99", "group", "1", "daily", "2026-09-27",
            json.dumps({"text": "synthetic", "intent": "news", "fingerprints": ["fp"]}), 2**52)
    else:
        _, _, spec = make_source(client, kind)
    plan = build_plan(spec, outbound_max_records=20, outbound_ttl=86400,
                      history_max_records=1000, utc_offset_seconds=28800)
    return spec, plan


@pytest.mark.parametrize("kind", ["followup", "reminder", "periodic"])
@pytest.mark.parametrize("owner", [False, True])
def test_activation_uses_frozen_tasks_and_owner_time_policy(isolated_redis, kind, owner):
    client = isolated_redis
    spec, plan = planned(client, kind)
    store = DeliveryStore(client, require_effects=True)
    claim = store.claim(spec, plan=plan)
    assert claim.ok
    before = json.loads(client.get(store.key(spec.action_id)))
    assert before["plan_json"] == plan.raw
    assert all(task["state"] == "not_started" for task in before["effects"])
    if owner:
        assert store.mark_unknown(spec.action_id, claim.token).ok
        assert store.reconcile(spec.action_id, delivered=True, operator_id="99").ok
    else:
        assert store.begin_send(spec, claim.token).ok
        assert store.mark_sent(spec.action_id, claim.token).ok
    raw = client.get(store.key(spec.action_id))
    action = json.loads(raw)
    assert action["state"] == "sent" and action["plan_json"] == plan.raw
    assert action["confirmation_source"] == ("owner" if owner else "transport")
    assert action["delivered_at_ms"] is None
    assert len(action["effects"]) == len(before["effects"])
    for task in action["effects"]:
        data = json.loads(task["payload_json"])
        assert task["payload_digest"] == hashlib.sha1(task["payload_json"].encode()).hexdigest()
        source = task["kind"].endswith("_complete")
        if source:
            assert task["state"] == "pending" and task["time_basis"] == "none"
        else:
            assert data["sent_at_ms"] == (None if owner else action["sent_recorded_at_ms"])
            assert task["state"] == ("needs_review" if owner else "pending")
    assert store.mark_sent(spec.action_id, claim.token).code == "already_sent"
    if owner:
        assert store.reconcile(spec.action_id, delivered=True, operator_id="100").code == "already_reconciled"
    assert client.get(store.key(spec.action_id)) == raw
    if kind != "periodic":
        assert SourceEffectWriter(client).complete_effect(source_effect_id(spec), spec) == "applied"
        assert SourceEffectWriter(client).complete_effect(source_effect_id(spec), spec) == "already_applied"
        assert client.get(store.key(spec.action_id)) == raw


@pytest.mark.parametrize("owner", [False, True])
def test_lost_sent_response_does_not_rebuild_or_reset_tasks(isolated_redis, owner):
    client = isolated_redis
    spec, plan = planned(client, "periodic")
    store = DeliveryStore(client, require_effects=True)
    claim = store.claim(spec, plan=plan)
    if owner:
        store.mark_unknown(spec.action_id, claim.token)
    else:
        store.begin_send(spec, claim.token)

    def lose_response(*args):
        result = client.eval(*args)
        if args[5] in {"sent", "reconcile_sent"}:
            raise ConnectionError("synthetic response lost")
        return result

    uncertain = DeliveryStore(SimpleNamespace(eval=lose_response), require_effects=True)
    with pytest.raises(DeliveryUnavailable):
        if owner:
            uncertain.reconcile(spec.action_id, delivered=True, operator_id="99")
        else:
            uncertain.mark_sent(spec.action_id, claim.token)
    key = store.key(spec.action_id)
    action = json.loads(client.get(key))
    # Model an independent worker already finishing one task before ACK retry.
    action["effects"][0]["state"] = "complete"
    client.set(key, json.dumps(action))
    first = client.get(key)
    if owner:
        assert store.reconcile(spec.action_id, delivered=True, operator_id="100").ok
    assert store.mark_sent(spec.action_id, claim.token).ok
    assert client.get(key) == first


def test_recovery_preserves_original_retention_despite_configuration_change(isolated_redis):
    client = isolated_redis
    spec, plan = planned(client, "followup")
    store = DeliveryStore(client, require_effects=True)
    claim = store.claim(spec, plan=plan)
    assert store.reject_before_send(spec.action_id, claim.token).ok
    altered = build_plan(spec, outbound_max_records=99, outbound_ttl=999999, utc_offset_seconds=0)
    recovered = store.recover(spec, plan=altered)
    assert recovered.ok
    action = json.loads(client.get(store.key(spec.action_id)))
    assert action["plan_json"] == plan.raw and action["plan_digest"] == plan.digest
    assert store.begin_send(spec, recovered.token).ok


def test_strict_protocol_rejects_missing_plan_then_installs_only_before_send(isolated_redis):
    client = isolated_redis
    spec, plan = planned(client, "reminder")
    strict = DeliveryStore(client, require_effects=True)
    with pytest.raises(DeliveryUnavailable):
        strict.claim(spec)
    assert not client.exists(strict.key(spec.action_id))
    legacy = DeliveryStore(client)
    old = legacy.claim(spec)
    assert strict.begin_send(spec, old.token).code == "plan_required"
    assert legacy.reject_before_send(spec.action_id, old.token).ok
    upgraded = strict.recover(spec, plan=plan)
    assert upgraded.ok and strict.begin_send(spec, upgraded.token).ok


@pytest.mark.parametrize("stage", ["begin", "sent", "owner"])
def test_corrupted_plan_cannot_advance_to_send_or_sent(isolated_redis, stage):
    client = isolated_redis
    spec, plan = planned(client, "periodic")
    store = DeliveryStore(client, require_effects=True)
    claim = store.claim(spec, plan=plan)
    if stage == "sent":
        assert store.begin_send(spec, claim.token).ok
    elif stage == "owner":
        assert store.mark_unknown(spec.action_id, claim.token).ok
    key = store.key(spec.action_id)
    action = json.loads(client.get(key))
    action["effects"][0]["payload_json"] = "{}"
    client.set(key, json.dumps(action))
    before = client.get(key)
    with pytest.raises(DeliveryUnavailable):
        if stage == "begin":
            store.begin_send(spec, claim.token)
        elif stage == "sent":
            store.mark_sent(spec.action_id, claim.token)
        else:
            store.reconcile(spec.action_id, delivered=True, operator_id="99")
    assert client.get(key) == before


def test_plan_rejects_missing_effect_and_wrong_source_before_redis(isolated_redis):
    client = isolated_redis
    spec, plan = planned(client, "periodic")
    data = json.loads(plan.raw)
    data["tasks"].pop()
    with pytest.raises(ValueError):
        DeliveryStore(client).claim(spec, plan=EffectPlan(json.dumps(data)))
    assert not client.exists(DeliveryStore.key(spec.action_id))
    source_spec, _ = planned(client, "reminder")
    with pytest.raises(ValueError):
        build_plan(replace(source_spec, source_key="unrelated"))


def test_manual_abandonment_never_activates_plan_or_accepts_late_ack(isolated_redis):
    client = isolated_redis
    spec, plan = planned(client, "followup")
    store = DeliveryStore(client, require_effects=True)
    claim = store.claim(spec, plan=plan)
    assert store.mark_unknown(spec.action_id, claim.token).ok
    assert store.reconcile(spec.action_id, delivered=False, operator_id="99").ok
    key = store.key(spec.action_id)
    before = client.get(key)
    action = json.loads(before)
    assert all(task["state"] == "not_started" for task in action["effects"])
    assert "sent_recorded_at_ms" not in action
    assert not store.mark_sent(spec.action_id, claim.token).ok
    assert SourceEffectWriter(client).complete_effect(source_effect_id(spec), spec) == "wrong_action"
    assert client.get(key) == before
