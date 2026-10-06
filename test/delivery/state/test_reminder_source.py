import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest

from src.models.schemas import ReminderRecord
from src.services.delivery.state import DeliverySpec, DeliveryStore
from src.services.persistence.reminder_state import (
    INTENT_KEY, REVISION_KEY, ReminderPersistenceUnavailable, ReminderStateStore,
)
from test.autonomy.test_pending_atomic import isolated_redis


def record(client, job_id="fixture", content="body", delta=3600):
    seconds, _ = client.time()
    return ReminderRecord(reminder_id=job_id, session_id="group_1", user_id=7, group_id=1,
                          content=content, remind_time=datetime.fromtimestamp(seconds) + timedelta(seconds=delta))


def execution(snapshot):
    item = snapshot.record
    spec = DeliverySpec("reminder", snapshot.intent["bot_id"], "group", str(item.group_id),
                        item.reminder_id, snapshot.revision, item.content, 2**52,
                        "reminders", item.reminder_id, snapshot.digest, REVISION_KEY)
    return spec


def test_create_persists_record_revision_and_scheduler_intent_together(isolated_redis):
    store = ReminderStateStore(isolated_redis)
    item = record(isolated_redis)
    result = store.create(item, bot_id="99")
    assert result.ok
    snapshot = result.snapshot
    assert store.load("fixture") == snapshot
    assert snapshot.record == item
    assert isolated_redis.hget(REVISION_KEY, "fixture") == snapshot.revision
    assert snapshot.intent["operation"] == "upsert"
    assert snapshot.intent["remind_at_ms"] == int(item.remind_time.timestamp() * 1000)
    assert not store.create(item, bot_id="99").ok


def test_wrong_intent_key_type_cannot_partially_write_reminder(isolated_redis):
    isolated_redis.set(INTENT_KEY, "wrong type")
    with pytest.raises(ReminderPersistenceUnavailable):
        ReminderStateStore(isolated_redis).create(record(isolated_redis), bot_id="99")
    assert not isolated_redis.exists("reminders")
    assert not isolated_redis.exists(REVISION_KEY)


def test_parallel_replacements_only_one_snapshot_wins(isolated_redis):
    store = ReminderStateStore(isolated_redis)
    old = store.create(record(isolated_redis), bot_id="99").snapshot
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda content: store.replace(
            old, old.record.model_copy(update={"content": content}), bot_id="99"), ["a", "b"]))
    assert sum(item.ok for item in results) == 1
    current = store.load("fixture")
    assert current.revision != old.revision
    assert not store.cancel(old).ok
    ledger = DeliveryStore(isolated_redis)
    assert ledger.claim(execution(old)).code == "source_changed"


def test_cancel_invalidates_queued_send_and_keeps_cancellation_intent(isolated_redis):
    store = ReminderStateStore(isolated_redis)
    old = store.create(record(isolated_redis), bot_id="99").snapshot
    ledger = DeliveryStore(isolated_redis)
    spec = execution(old)
    claim = ledger.claim(spec)
    cancelled = store.cancel(old, action_key=ledger.key(spec.action_id))
    assert cancelled.ok and cancelled.delivery_state == "queued"
    assert store.load("fixture") is None
    intent = json.loads(isolated_redis.hget(INTENT_KEY, "fixture"))
    assert intent["operation"] == "cancel"
    assert not ledger.begin_send(spec, claim.token).ok
    recreated = store.create(record(isolated_redis, content="explicit recreation"), bot_id="99")
    assert recreated.ok and recreated.snapshot.revision != old.revision
    assert not ledger.begin_send(spec, claim.token).ok


def test_sending_cancel_reports_uncertainty_without_erasing_execution(isolated_redis):
    store = ReminderStateStore(isolated_redis)
    old = store.create(record(isolated_redis), bot_id="99").snapshot
    ledger = DeliveryStore(isolated_redis)
    spec = execution(old)
    claim = ledger.claim(spec)
    assert ledger.begin_send(spec, claim.token).ok
    result = store.cancel(old, action_key=ledger.key(spec.action_id))
    assert result.ok and result.delivery_state == "sending"
    assert ledger.inspect(spec.action_id).state == "sending"
    assert not store.complete(old, action_key=ledger.key(spec.action_id)).ok


def test_complete_requires_matching_sent_record_and_is_idempotent(isolated_redis):
    store = ReminderStateStore(isolated_redis)
    old = store.create(record(isolated_redis), bot_id="99").snapshot
    ledger = DeliveryStore(isolated_redis)
    spec = execution(old)
    claim = ledger.claim(spec)
    action_key = ledger.key(spec.action_id)
    assert not store.complete(old, action_key=action_key).ok
    assert ledger.begin_send(spec, claim.token).ok
    assert ledger.mark_sent(spec.action_id, claim.token).ok
    assert store.complete(old, action_key=action_key).ok
    assert store.complete(old, action_key=action_key).code == "already_completed"
    assert store.load("fixture") is None


def test_late_sent_old_revision_cannot_clear_replacement(isolated_redis):
    store = ReminderStateStore(isolated_redis)
    old = store.create(record(isolated_redis), bot_id="99").snapshot
    ledger = DeliveryStore(isolated_redis)
    spec = execution(old)
    claim = ledger.claim(spec)
    assert ledger.begin_send(spec, claim.token).ok
    updated = store.replace(old, record(isolated_redis, content="new"), bot_id="99",
                            action_key=ledger.key(spec.action_id))
    assert updated.ok and updated.delivery_state == "sending"
    assert ledger.mark_sent(spec.action_id, claim.token).ok
    assert not store.complete(old, action_key=ledger.key(spec.action_id)).ok
    assert store.load("fixture") == updated.snapshot


def test_sent_action_without_source_binding_cannot_clear_reminder(isolated_redis):
    store = ReminderStateStore(isolated_redis)
    old = store.create(record(isolated_redis), bot_id="99").snapshot
    ledger = DeliveryStore(isolated_redis)
    spec = replace(execution(old), source_key="", source_field="", source_digest="", revision_key="")
    claim = ledger.claim(spec)
    assert ledger.begin_send(spec, claim.token).ok
    assert ledger.mark_sent(spec.action_id, claim.token).ok
    assert store.complete(old, action_key=ledger.key(spec.action_id)).code == "wrong_action"
    assert store.load("fixture") == old


def test_only_future_legacy_migrates_and_first_bot_binding_is_stable(isolated_redis):
    store = ReminderStateStore(isolated_redis)
    for name, delta in [("future", 3600), ("overdue", -60)]:
        item = record(isolated_redis, job_id=name, delta=delta)
        isolated_redis.hset("reminders", name, item.model_dump_json())
    overdue = store.load("overdue")
    assert store.migrate_future(overdue).code == "overdue"
    assert store.load("overdue") == overdue
    migrated = store.migrate_future(store.load("future"))
    assert migrated.ok and migrated.snapshot.intent["bot_id"] == ""
    assert migrated.snapshot.intent["grace_seconds"] == 300
    bound = store.bind_bot(migrated.snapshot, "99")
    assert bound.ok
    assert store.bind_bot(migrated.snapshot, "100").code == "wrong_bot"
    assert store.load("future").intent["bot_id"] == "99"


@pytest.mark.parametrize("client", [None, Mock(eval=Mock(side_effect=ConnectionError))])
def test_outage_has_no_memory_fallback(client):
    with pytest.raises(ReminderPersistenceUnavailable):
        ReminderStateStore(client).load("fixture")
