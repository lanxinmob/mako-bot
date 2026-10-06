from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from src.services.persistence.effects import EffectNeedsReview, EffectUnavailable
from src.services.persistence.history_commit.delivery import HistoryDeliveryStore
from src.services.persistence.history_commit.plans import HistoryDeliveryPlan, MAX_TIMESTAMP_MS, build_plan, canonical
from src.services.persistence.history_commit.snapshot import HistorySnapshots
from test.autonomy.test_pending_atomic import isolated_redis


@pytest.fixture
def planned(isolated_redis):
    snapshot = HistorySnapshots(isolated_redis).read("group_8")
    plan = build_plan("a" * 64, snapshot, bot_id="99", user_id=7, group_id=8,
                      text="reply", history=[{"role": "assistant", "content": "reply"}],
                      max_history_turns=2, global_max_records=1000, utc_offset_seconds=28800)
    return isolated_redis, HistoryDeliveryStore(isolated_redis), plan


def test_only_acknowledged_send_activates_frozen_tasks_and_time(planned):
    client, store, plan = planned
    token = store.create(plan)
    seconds, micros = client.time()
    recorded = seconds * 1000 + micros // 1000
    assert token and store.create(plan) is None
    before = store.inspect(plan.action_id)
    assert before.state == "prepared" and before.plan == plan
    assert json.loads(before.raw)["tasks"] == {"session": "dormant", "global": "dormant"}
    assert store.transition(plan.action_id, token, "sent", delivered_at_ms=recorded) == "denied"
    assert store.transition(plan.action_id, "b" * 64, "begin") == "denied"
    assert store.transition(plan.action_id, token, "begin") == "sending"
    assert store.transition(plan.action_id, token, "begin") == "denied"
    assert store.transition(plan.action_id, token, "unknown") == "unknown"
    unknown = store.inspect(plan.action_id)
    assert unknown.delivered_at_ms is None
    assert json.loads(unknown.raw)["tasks"] == {"session": "dormant", "global": "dormant"}
    assert store.transition(plan.action_id, token, "begin") == "denied"
    assert store.transition(plan.action_id, token, "sent", delivered_at_ms=recorded) == "sent"
    sent = store.inspect(plan.action_id)
    assert sent.delivered_at_ms == recorded
    assert json.loads(sent.raw)["tasks"] == {"session": "pending", "global": "pending"}
    assert store.transition(plan.action_id, token, "sent", delivered_at_ms=recorded) == "sent"
    assert store.transition(plan.action_id, token, "sent", delivered_at_ms=recorded + 1) == "denied"
    assert store.inspect(plan.action_id).raw == sent.raw
    assert store.transition(plan.action_id, token, "unknown") == "denied"
    assert client.ttl(store.key(plan.action_id)) == -1
    assert not client.exists("chat:history:group_8", "all_memory")


def test_creation_response_loss_never_returns_new_permission(planned):
    client, store, plan = planned

    def lost(*args):
        client.eval(*args)
        raise ConnectionError("synthetic plan response loss")

    with pytest.raises(EffectUnavailable):
        HistoryDeliveryStore(SimpleNamespace(eval=lost)).create(plan)
    assert store.create(plan) is None
    assert store.inspect(plan.action_id).state == "prepared"


def test_begin_response_loss_stops_transport_and_cannot_reacquire(planned):
    client, store, plan = planned
    token = store.create(plan)

    def lost(*args):
        client.eval(*args)
        raise ConnectionError("synthetic begin response loss")

    broken = HistoryDeliveryStore(SimpleNamespace(get=client.get, eval=lost))
    with pytest.raises(EffectUnavailable):
        broken.transition(plan.action_id, token, "begin")
    assert store.inspect(plan.action_id).state == "sending"
    assert store.transition(plan.action_id, token, "begin") == "denied"
    assert store.transition(plan.action_id, token, "unknown") == "unknown"


def test_reject_before_send_and_missing_records_never_activate(planned):
    client, store, plan = planned
    token = store.create(plan)
    assert store.transition(plan.action_id, token, "reject") == "rejected"
    assert store.transition(plan.action_id, token, "begin") == "denied"
    assert store.transition(plan.action_id, token, "sent", delivered_at_ms=1) == "denied"
    assert json.loads(store.inspect(plan.action_id).raw)["tasks"] == {"session": "dormant", "global": "dormant"}
    client.delete(store.key(plan.action_id))
    assert store.transition(plan.action_id, token, "sent", delivered_at_ms=1) == "missing"
    assert store.inspect(plan.action_id) is None


def test_full_unicode_body_and_original_snapshot_survive_plan_serialization(planned):
    client, store, _ = planned
    source = ' [ {"role":"user", "content":"原文", "extra":true} ] '
    client.set("group_8", source)
    snapshot = HistorySnapshots(client).read("group_8")
    text = "中文正文" * 5000
    plan = build_plan("c" * 64, snapshot, bot_id="99", user_id=7, group_id=8,
                      text=text, history=[{"role": "assistant", "content": text}],
                      max_history_turns=2, global_max_records=1000, utc_offset_seconds=28800)
    assert store.create(plan)
    frozen = store.inspect(plan.action_id).plan
    assert frozen.data()["text"] == text
    assert frozen.snapshot().raw == source.encode("utf-8")
    assert frozen.data()["history"][0]["content"] == text
    data = plan.data()
    data["text"] = "太长" * 400000
    with pytest.raises(ValueError, match="capacity"):
        HistoryDeliveryPlan(canonical(data))
    assert not client.exists("chat:history:group_8")


def test_binding_corruption_and_volatile_delivery_stop_transitions(planned):
    client, store, plan = planned
    token = store.create(plan)
    key = store.key(plan.action_id)
    client.pexpire(key, 60000)
    with pytest.raises(EffectNeedsReview):
        store.transition(plan.action_id, token, "begin")
    assert store.inspect(plan.action_id).state == "prepared"
    data = json.loads(client.get(key))
    data["digest"] = "b" * 64
    client.set(key, json.dumps(data))
    with pytest.raises(EffectNeedsReview):
        store.inspect(plan.action_id)
    modified = plan.data()
    modified["group_id"] = 9
    with pytest.raises(ValueError, match="target"):
        replace(plan, raw=canonical(modified))


def test_ack_time_boundary_is_exact_and_oversize_never_mutates(planned):
    client, store, plan = planned
    token = store.create(plan)
    assert store.transition(plan.action_id, token, "begin") == "sending"
    before = client.dump(store.key(plan.action_id))
    for invalid in (MAX_TIMESTAMP_MS + 1, 100000000000001, 9007199254740991):
        with pytest.raises(ValueError, match="capacity"):
            store.transition(plan.action_id, token, "sent", delivered_at_ms=invalid)
        assert client.dump(store.key(plan.action_id)) == before
    assert store.transition(plan.action_id, token, "sent", delivered_at_ms=MAX_TIMESTAMP_MS) == "sent"
    assert store.inspect(plan.action_id).delivered_at_ms == MAX_TIMESTAMP_MS
    assert store.transition(plan.action_id, token, "sent", delivered_at_ms=MAX_TIMESTAMP_MS) == "sent"


def test_server_created_and_begin_time_are_checked_before_mutation(planned):
    client, store, plan = planned

    def extreme(*args):
        script = args[0].replace("redis.call('TIME')", "{100000000000, 1000}")
        return client.eval(script, *args[1:])

    broken = HistoryDeliveryStore(SimpleNamespace(get=client.get, eval=extreme))
    with pytest.raises(EffectNeedsReview):
        broken.create(plan)
    assert not client.exists(store.key(plan.action_id))
    token = store.create(plan)
    before = client.dump(store.key(plan.action_id))
    with pytest.raises(EffectNeedsReview):
        broken.transition(plan.action_id, token, "begin")
    assert client.dump(store.key(plan.action_id)) == before
