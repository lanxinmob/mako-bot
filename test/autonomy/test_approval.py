import json
from dataclasses import asdict
from unittest.mock import Mock

import pytest

from src.services.autonomy.approval import ApprovalStore, ApprovalUnavailable
from src.services.autonomy.models import PendingAction
from test.autonomy.test_pending_atomic import isolated_redis


@pytest.fixture
def approval(isolated_redis):
    client = isolated_redis
    seconds, micros = client.time()
    pending = PendingAction("p1", "group", 7, "original", "fixture", seconds + micros / 1e6)
    client.set("autonomy:pending:p1", json.dumps(asdict(pending)))
    client.set("autonomy:pending:latest", "p1")
    store = ApprovalStore(client, pending_ttl_seconds=300)
    return client, store, store.load_latest()


def test_claim_fencing_and_approved_text(approval):
    client, store, snapshot = approval
    first = store.claim(snapshot, "replacement")
    assert first.ok
    assert not store.claim(snapshot, "different").ok
    assert not store.begin_send(snapshot, "wrong-token", "replacement").ok
    assert not store.begin_send(snapshot, first.token, "original").ok
    assert store.begin_send(snapshot, first.token, "replacement").ok
    assert not store.begin_send(snapshot, first.token, "replacement").ok
    assert not store.cancel(snapshot).ok
    assert store.mark_unknown("p1", first.token).ok
    assert not store.claim(snapshot, "replacement").ok
    assert client.ttl("autonomy:execution:p1") == -1


def test_cancel_queued_prevents_send_and_preserves_new_latest(approval):
    client, store, snapshot = approval
    first = store.claim(snapshot, "original")
    cancelled = store.cancel(snapshot)
    assert cancelled.ok
    assert not store.begin_send(snapshot, first.token, "original").ok
    assert not store.reject_before_send("p1", first.token).ok
    client.set("autonomy:pending:latest", "new")
    assert store.cleanup("p1", cancelled.token).ok
    assert client.get("autonomy:pending:latest") == "new"
    assert client.get("autonomy:pending:p1") is None


def test_expired_queue_fences_old_token_but_sending_never_reclaims(approval):
    client, store, snapshot = approval
    old = store.claim(snapshot, "original")
    state = json.loads(client.get("autonomy:execution:p1"))
    state["lease_until_ms"] = 0
    client.set("autonomy:execution:p1", json.dumps(state))
    new = store.claim(snapshot, "replacement")
    assert new.ok and new.token != old.token
    assert not store.reject_before_send("p1", old.token).ok
    assert store.begin_send(snapshot, new.token, "replacement").ok
    state = json.loads(client.get("autonomy:execution:p1"))
    state["lease_until_ms"] = 0
    client.set("autonomy:execution:p1", json.dumps(state))
    assert store.inspect("p1").state == "unknown"
    assert not store.claim(snapshot, "replacement").ok


def test_pending_change_and_confirmed_delivery(approval):
    client, store, snapshot = approval
    claim = store.claim(snapshot, "original")
    raw = client.get("autonomy:pending:p1")
    client.set("autonomy:pending:p1", raw + " ")
    assert not store.begin_send(snapshot, claim.token, "original").ok
    client.set("autonomy:pending:p1", raw)
    assert store.begin_send(snapshot, claim.token, "original").ok
    assert store.mark_sent("p1", claim.token).ok
    assert not store.mark_unknown("p1", claim.token).ok
    assert not store.claim(snapshot, "original").ok
    assert store.cleanup("p1", claim.token).ok
    assert store.inspect("p1").state == "sent"


@pytest.mark.parametrize("client", [None, Mock(get=Mock(side_effect=ConnectionError))])
def test_unavailable_never_falls_back(client):
    with pytest.raises(ApprovalUnavailable):
        ApprovalStore(client, pending_ttl_seconds=300).load_latest()
