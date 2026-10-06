"""Legacy classification preserves evidence and never reconstructs effects."""
import json
from types import SimpleNamespace

import pytest

from src.services.delivery.effects.discovery import EffectScanner
from src.services.delivery.state.effect_legacy import classify_legacy_sent
from src.services.persistence.effects import EffectUnavailable
from test.autonomy.test_pending_atomic import isolated_redis
from test.delivery.state.test_store import delivery


def legacy_sent(delivery):
    client, store, spec = delivery
    claimed = store.claim(spec)
    assert store.begin_send(spec, claimed.token).ok
    assert store.mark_sent(spec.action_id, claimed.token).ok
    return client, store.key(spec.action_id), spec.action_id


@pytest.mark.asyncio
async def test_discovery_classifies_legacy_without_replay(delivery):
    client, key, action_id = legacy_sent(delivery)
    before = json.loads(client.get(key))
    page = await EffectScanner(client).run_page()
    assert page.outcomes == ((action_id, "legacy_review"),)
    after = json.loads(client.get(key))
    assert after.pop("effects_review_reason") == "legacy_effects_unverified"
    assert after.pop("effects_state") == "needs_review"
    before.pop("effects_state")
    assert after == before
    assert list(client.scan_iter()) == [key]
    first = client.dump(key)
    await EffectScanner(client).run_page()
    assert client.dump(key) == first and client.ttl(key) == -1


@pytest.mark.parametrize("change", [
    {"state": "unknown"}, {"effects_version": 2}, {"plan_json": "broken"},
    {"digest": "wrong"}, {"effects_state": "complete"},
    {"effects_state": "needs_review", "effects_review_reason": "actual_delivery_time_unknown"},
])
def test_unproven_or_already_reviewed_records_unchanged(delivery, change):
    client, key, action_id = legacy_sent(delivery)
    raw = json.loads(client.get(key))
    raw.update(change)
    client.set(key, json.dumps(raw))
    before = client.dump(key)
    assert classify_legacy_sent(client, action_id) == "needs_review"
    assert client.dump(key) == before


@pytest.mark.parametrize("race", ["replace", "delete", "expiry"])
def test_cas_does_not_overwrite_changed_or_expiring_evidence(delivery, race):
    client, key, action_id = legacy_sent(delivery)
    original = client.get(key)

    def interleave(*args):
        if race == "replace":
            client.set(key, "new concurrent evidence")
        elif race == "delete":
            client.delete(key)
        else:
            client.pexpire(key, 60000)
        return client.eval(*args)

    result = classify_legacy_sent(SimpleNamespace(get=client.get, eval=interleave), action_id)
    assert result == {"replace": "changed", "delete": "missing", "expiry": "needs_review"}[race]
    assert client.get(key) == {"replace": "new concurrent evidence", "delete": None, "expiry": original}[race]
    if race == "expiry":
        assert 0 < client.pttl(key) <= 60000


def test_lost_classification_response_retains_idempotent_result(delivery):
    client, key, action_id = legacy_sent(delivery)

    def lost_response(*args):
        client.eval(*args)
        raise ConnectionError("synthetic response loss")

    with pytest.raises(EffectUnavailable):
        classify_legacy_sent(SimpleNamespace(get=client.get, eval=lost_response), action_id)
    first = client.dump(key)
    assert classify_legacy_sent(client, action_id) == "needs_review"
    assert client.dump(key) == first
