from concurrent.futures import ThreadPoolExecutor
import json
from types import SimpleNamespace

import pytest

from src.services.persistence.effects import EffectNeedsReview, EffectUnavailable
from src.services.persistence.history_commit.reconciliation import HistoryReconciliation
from src.services.persistence.history_commit.tasks import HistoryEffects
from test.autonomy.test_pending_atomic import isolated_redis
from test.persistence.history_commit.test_delivery import planned


@pytest.fixture
def unknown(planned):
    client, delivery, plan = planned
    token = delivery.create(plan)
    assert delivery.transition(plan.action_id, token, "begin") == "sending"
    assert delivery.transition(plan.action_id, token, "unknown") == "unknown"
    return client, delivery, plan, token, HistoryReconciliation(client)


@pytest.mark.parametrize("delivered", [True, False])
def test_owner_conclusion_is_terminal_and_never_invents_delivery_time(unknown, delivered):
    client, delivery, plan, token, store = unknown
    outcome = "sent" if delivered else "abandoned"
    assert store.reconcile(plan.action_id, delivered=delivered, operator_id="7") == outcome
    key = delivery.key(plan.action_id)
    saved = client.get(key)
    data = json.loads(saved)
    assert data["confirmation_source"] == "owner" and data["owner_id"] == "7"
    assert data["owner_conclusion"] == outcome and data["reviewed_at_ms"] > 0
    assert data["delivered_at_ms"] is None
    expected = "needs_review" if delivered else "dormant"
    assert data["tasks"] == {"session": expected, "global": expected}
    assert store.reconcile(plan.action_id, delivered=delivered, operator_id="8") == outcome
    assert store.reconcile(plan.action_id, delivered=not delivered, operator_id="8") == "denied"
    assert client.get(key) == saved
    assert delivery.transition(plan.action_id, token, "sent", delivered_at_ms=1791240000123) == "denied"
    assert delivery.transition(plan.action_id, token, "begin") == "denied"
    assert client.get(key) == saved and client.pttl(key) == -1
    effects = HistoryEffects(client)
    assert effects.claim(plan.action_id, "session") is None
    assert effects.claim(plan.action_id, "global") is None
    assert not client.exists("all_memory", "chat:history:group_8")


def test_concurrent_manual_conclusions_have_one_winner(unknown):
    client, delivery, plan, token, store = unknown
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda delivered: store.reconcile(plan.action_id, delivered=delivered, operator_id="7"),
                                [True, False]))
    assert len([result for result in results if result in {"sent", "abandoned"}]) == 1
    assert all(result in {"sent", "abandoned", "changed", "denied"} for result in results)
    data = json.loads(client.get(delivery.key(plan.action_id)))
    assert data["state"] == data["owner_conclusion"] and data["delivered_at_ms"] is None


def test_lost_owner_write_response_keeps_same_conclusion_and_operator(unknown):
    client, delivery, plan, token, store = unknown

    def lost(*args):
        client.eval(*args)
        raise ConnectionError("synthetic owner response loss")

    broken = HistoryReconciliation(SimpleNamespace(get=client.get, eval=lost))
    with pytest.raises(EffectUnavailable):
        broken.reconcile(plan.action_id, delivered=True, operator_id="7")
    before = client.dump(delivery.key(plan.action_id))
    assert store.reconcile(plan.action_id, delivered=True, operator_id="8") == "sent"
    assert client.dump(delivery.key(plan.action_id)) == before


def test_late_ack_wins_cas_before_owner_and_known_time_remains(unknown):
    client, delivery, plan, token, store = unknown

    def completed_first(*args):
        assert delivery.transition(plan.action_id, token, "sent", delivered_at_ms=1791240000123) == "sent"
        return client.eval(*args)

    interleaved = HistoryReconciliation(SimpleNamespace(get=client.get, eval=completed_first))
    assert interleaved.reconcile(plan.action_id, delivered=True, operator_id="7") == "changed"
    actual = delivery.inspect(plan.action_id)
    assert actual.delivered_at_ms == 1791240000123
    assert store.reconcile(plan.action_id, delivered=False, operator_id="7") == "denied"


def test_volatile_and_malformed_manual_evidence_stops_reconciliation(unknown):
    client, delivery, plan, token, store = unknown
    key = delivery.key(plan.action_id)
    client.pexpire(key, 60000)
    before = client.dump(key)
    with pytest.raises(EffectNeedsReview):
        store.reconcile(plan.action_id, delivered=True, operator_id="7")
    assert client.dump(key) == before and client.pttl(key) > 0
    client.persist(key)
    assert store.reconcile(plan.action_id, delivered=True, operator_id="7") == "sent"
    original = json.loads(client.get(key))
    for field in ("owner_id", "owner_conclusion", "reviewed_at_ms", "delivered_at_ms"):
        data = json.loads(json.dumps(original))
        del data[field]
        client.set(key, json.dumps(data))
        before = client.dump(key)
        with pytest.raises(EffectNeedsReview):
            store.reconcile(plan.action_id, delivered=True, operator_id="7")
        assert client.dump(key) == before
    for field, value in (("confirmation_source", "other"), ("confirmation_source", "transport"),
                         ("owner_id", "0"), ("owner_id", "9007199254740992"),
                         ("reviewed_at_ms", 99999999999999 + 1), ("reviewed_at_ms", True),
                         ("delivered_at_ms", 1791240000123), ("owner_conclusion", "abandoned"),
                         ("task_meta", {"session": {"token": "b" * 64}})):
        data = json.loads(json.dumps(original))
        data[field] = value
        client.set(key, json.dumps(data))
        before = client.dump(key)
        with pytest.raises(EffectNeedsReview):
            HistoryEffects(client).inspect(plan.action_id)
        assert client.dump(key) == before
    data = json.loads(json.dumps(original))
    data["tasks"]["global"] = "pending"
    client.set(key, json.dumps(data))
    with pytest.raises(EffectNeedsReview):
        HistoryEffects(client).claim(plan.action_id, "global")
