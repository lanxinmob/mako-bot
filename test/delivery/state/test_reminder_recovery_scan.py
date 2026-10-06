from unittest.mock import Mock

import pytest

from src.services.persistence.reminder_state import (
    INTENT_KEY, ReminderPersistenceUnavailable, ReminderStateStore,
)
from test.autonomy.test_pending_atomic import isolated_redis
from test.delivery.state.test_reminder_source import record


def collect_ids(store, *, intents):
    cursor, found = 0, set()
    while True:
        cursor, ids = store.scan_ids(cursor, intents=intents, count=1)
        found.update(ids)
        if cursor == 0:
            return found


def test_recovery_finds_legacy_sources_and_cancelled_intents(isolated_redis):
    store = ReminderStateStore(isolated_redis)
    legacy = record(isolated_redis, job_id="legacy")
    isolated_redis.hset("reminders", "legacy", legacy.model_dump_json())
    active = store.create(record(isolated_redis, job_id="active"), bot_id="99")
    cancelled = store.create(record(isolated_redis, job_id="cancelled"), bot_id="99")
    assert active.ok and store.cancel(cancelled.snapshot).ok
    assert collect_ids(store, intents=False) == {"legacy", "active"}
    assert collect_ids(store, intents=True) == {"active", "cancelled"}
    assert store.load("cancelled") is None


def test_empty_nonterminal_page_and_bytes_ids_preserve_cursor():
    client = Mock()
    client.hscan.side_effect = [(17, {}), (0, {b"job": b"not read as authority"})]
    store = ReminderStateStore(client)
    assert store.scan_ids(intents=True) == (17, ())
    assert store.scan_ids(17, intents=True) == (0, ("job",))
    client.hscan.assert_called_with(INTENT_KEY, cursor=17, count=100)
    client.eval.assert_not_called()


@pytest.mark.parametrize("client", [None, Mock(hscan=Mock(side_effect=ConnectionError))])
def test_scan_outage_never_looks_like_empty_recovery(client):
    with pytest.raises(ReminderPersistenceUnavailable):
        ReminderStateStore(client).scan_ids()


def test_wrong_key_type_retains_recovery_evidence(isolated_redis):
    isolated_redis.set(INTENT_KEY, "wrong type")
    with pytest.raises(ReminderPersistenceUnavailable):
        ReminderStateStore(isolated_redis).scan_ids(intents=True)
    assert isolated_redis.get(INTENT_KEY) == "wrong type"
