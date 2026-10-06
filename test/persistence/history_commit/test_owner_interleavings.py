import json
from types import SimpleNamespace

import pytest

from src.services.persistence.effects import EffectNeedsReview
from src.services.persistence.history_commit.delivery import HistoryDeliveryStore
from src.services.persistence.history_commit.reconciliation import HistoryReconciliation, RECONCILE
from src.services.persistence.history_commit.tasks import HistoryEffects
from test.autonomy.test_pending_atomic import isolated_redis
from test.persistence.history_commit.test_delivery import planned
from test.persistence.history_commit.test_reconciliation import unknown


@pytest.mark.parametrize("delivered", [True, False])
def test_owner_wins_between_late_ack_read_and_eval_without_overwrite(unknown, delivered):
    client, delivery, plan, token, owner = unknown
    key = delivery.key(plan.action_id)
    original = client.get(key)
    saved = {}

    def owner_writes_first(*args):
        assert args[3] == original
        outcome = owner.reconcile(plan.action_id, delivered=delivered, operator_id="7")
        assert outcome == ("sent" if delivered else "abandoned")
        saved["raw"] = client.get(key)
        return client.eval(*args)

    stale_ack = HistoryDeliveryStore(SimpleNamespace(get=client.get, eval=owner_writes_first))
    assert stale_ack.transition(plan.action_id, token, "sent", delivered_at_ms=1791240000123) == "changed"
    assert client.get(key) == saved["raw"] and client.pttl(key) == -1
    assert delivery.transition(plan.action_id, token, "sent", delivered_at_ms=1791240000123) == "denied"
    assert client.get(key) == saved["raw"]
    data = json.loads(saved["raw"])
    assert data["confirmation_source"] == "owner" and data["delivered_at_ms"] is None
    expected = "needs_review" if delivered else "dormant"
    assert data["tasks"] == {"session": expected, "global": expected}
    assert HistoryEffects(client).claim(plan.action_id, "global") is None
    assert not client.exists("all_memory", "chat:history:group_8")


def test_owner_read_then_new_ttl_refuses_write_without_extending_or_mutating(unknown):
    client, delivery, plan, token, owner = unknown
    key = delivery.key(plan.action_id)
    before = client.dump(key)

    def add_ttl_after_read(*args):
        assert args[0] == RECONCILE and args[3] == client.get(key)
        assert client.pttl(key) == -1
        client.pexpire(key, 60000)
        return client.eval(*args)

    interleaved = HistoryReconciliation(SimpleNamespace(get=client.get, eval=add_ttl_after_read))
    with pytest.raises(EffectNeedsReview):
        interleaved.reconcile(plan.action_id, delivered=True, operator_id="7")
    assert client.dump(key) == before and 0 < client.pttl(key) <= 60000
    assert delivery.inspect(plan.action_id).state == "unknown"
    assert not client.exists("all_memory", "chat:history:group_8")
