import json
from types import SimpleNamespace

import pytest

from src.services.persistence.effects import EffectNeedsReview
from src.services.persistence.history_commit.reconciliation import HistoryReconciliation
from test.autonomy.test_pending_atomic import isolated_redis
from test.persistence.history_commit.test_delivery import planned


def test_old_sending_only_classifies_and_original_token_accepts_late_ack(planned):
    client, store, plan = planned
    token = store.create(plan)
    store.transition(plan.action_id, token, "begin")
    key = store.key(plan.action_id)
    young = client.dump(key)
    classification = HistoryReconciliation(client)
    assert classification.classify(plan.action_id) == "unchanged" and client.dump(key) == young
    data = json.loads(client.get(key))
    seconds, micros = client.time()
    data["begun_at_ms"] = seconds * 1000 + micros // 1000 - 300001
    client.set(key, json.dumps(data))
    assert classification.classify(plan.action_id) == "send_unknown"
    classified = json.loads(client.get(key))
    assert {k: v for k, v in classified.items() if k not in {"state", "unknown_reason"}} == {
        k: v for k, v in data.items() if k != "state"}
    assert classified["tasks"] == {"session": "dormant", "global": "dormant"}
    assert not client.exists("all_memory", "chat:history:group_8")
    assert store.transition(plan.action_id, token, "begin") == "denied"
    assert store.transition(plan.action_id, token, "sent", delivered_at_ms=1791240000123) == "sent"
    assert store.inspect(plan.action_id).token == token


def test_classification_cas_and_volatile_record_preserve_late_completion(planned):
    client, store, plan = planned
    token = store.create(plan)
    store.transition(plan.action_id, token, "begin")
    key = store.key(plan.action_id)
    client.pexpire(key, 60000)
    before = client.dump(key)
    with pytest.raises(EffectNeedsReview):
        HistoryReconciliation(client).classify(plan.action_id)
    assert client.dump(key) == before and client.pttl(key) > 0
    client.persist(key)

    def interleaved(*args):
        assert store.transition(plan.action_id, token, "sent", delivered_at_ms=1791240000123) == "sent"
        return client.eval(*args)

    classifier = HistoryReconciliation(SimpleNamespace(get=client.get, eval=interleaved))
    assert classifier.classify(plan.action_id) == "changed"
    assert store.inspect(plan.action_id).state == "sent"
