from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.models.schemas import RelationshipMemory
from src.services.delivery.state.legacy import list_old_followups, list_retained_reminders
from src.services.delivery.state import DeliveryUnavailable
from src.services.persistence.followups import revision_key
from src.services.persistence.reminder_state import REVISION_KEY
from test.autonomy.owner_loader import load_owner
from test.autonomy.test_pending_atomic import isolated_redis
from test.delivery.state.test_reminder_source import record


def collect(reader, client):
    cursor, rows = "0:0", []
    for _ in range(100):
        page = reader(client, cursor, limit=1)
        assert len(page.entries) <= 1
        rows.extend(page.entries)
        cursor = page.next_cursor
        if cursor is None:
            return rows
    raise AssertionError("listing did not terminate")


def test_followups_find_both_legacy_indexes_without_mutation(isolated_redis):
    client = isolated_redis
    quarantine = "mako:delivery:v1:legacy:followups"
    for name, key, versioned in [("old", quarantine, False),
                                 ("not_scanned", "relationship:followups", False),
                                 ("new", "relationship:followups", True)]:
        memory = RelationshipMemory(memory_id=name, user_id=7, memory_type="promise",
            content="synthetic private content", due_at=datetime.now() - timedelta(hours=1))
        client.hset("relationship:7", name, memory.model_dump_json())
        client.zadd(key, {f"7:{name}": memory.due_at.timestamp()})
        if versioned:
            client.hset(revision_key(7), name, "revision")
    keys = [quarantine, "relationship:followups", "relationship:7", revision_key(7)]
    before = [client.dump(key) for key in keys]
    rows = collect(list_old_followups, client)
    assert {row.business_id for row in rows} == {"7:old", "7:not_scanned"}
    assert all(row.status == "legacy_unverified" for row in rows)
    assert "synthetic private content" not in repr(rows)
    assert [client.dump(key) for key in keys] == before


def test_reminders_show_legacy_and_overdue_without_initializing_revision(isolated_redis):
    client = isolated_redis
    for name, delta, versioned in [("legacy_future", 3600, False), ("legacy_past", -60, False),
                                  ("new_future", 3600, True), ("new_past", -60, True)]:
        item = record(client, job_id=name, delta=delta)
        client.hset("reminders", name, item.model_dump_json())
        if versioned:
            client.hset(REVISION_KEY, name, "revision")
    before = [client.dump(key) for key in ["reminders", REVISION_KEY]]
    rows = collect(list_retained_reminders, client)
    assert {row.business_id: row.status for row in rows} == {
        "legacy_future": "legacy_unverified", "legacy_past": "legacy_unverified",
        "new_past": "overdue_check_action"}
    assert [client.dump(key) for key in ["reminders", REVISION_KEY]] == before


def test_missing_and_invalid_followup_sources_are_visible(isolated_redis):
    client = isolated_redis
    client.zadd("mako:delivery:v1:legacy:followups", {"7:missing": 1, "7:invalid": 2})
    client.hset("relationship:7", "invalid", "not json")
    rows = collect(list_old_followups, client)
    assert {row.status for row in rows} == {"missing_source", "invalid_source"}
    assert client.hget("relationship:7", "invalid") == "not json"


@pytest.mark.parametrize("reader", [list_old_followups, list_retained_reminders])
def test_legacy_query_outage_does_not_claim_empty(reader):
    with pytest.raises(DeliveryUnavailable):
        reader(None)


@pytest.mark.asyncio
@pytest.mark.parametrize("command,reader", [("旧跟进列表", "list_old_followups"),
                                           ("提醒待核对", "list_retained_reminders")])
async def test_owner_query_route_never_migrates_or_sends(command, reader, monkeypatch):
    owner = load_owner()
    page_reader = Mock(return_value=SimpleNamespace(entries=(), next_cursor="1:0"))
    feedback = AsyncMock()
    monkeypatch.setitem(owner.process_delivery_command.__globals__, reader, page_reader)
    monkeypatch.setitem(owner.process_delivery_command.__globals__, "send_to_event", feedback)
    client = object()
    ctx = SimpleNamespace(settings=SimpleNamespace(autonomy_owner_id=99),
        repository=SimpleNamespace(redis_client=client), policy=SimpleNamespace(is_enabled=lambda: False))
    event = Mock(spec=owner.PrivateMessageEvent, user_id=99)
    event.get_plaintext.return_value = command
    bot = Mock()
    assert await owner.autonomy_rule(ctx, event)
    assert await owner.process_owner_private(ctx, bot, Mock(), event, command)
    page_reader.assert_called_once_with(client, "0:0")
    assert f"{command} 1:0" in feedback.call_args.args[2]
    assert not bot.mock_calls
