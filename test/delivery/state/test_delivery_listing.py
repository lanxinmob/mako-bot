from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.services.delivery.state import DeliveryUnavailable
from src.services.delivery.state import listing
from test.autonomy.test_pending_atomic import isolated_redis
from test.delivery.state.test_store import delivery


def test_lists_actual_actions_without_reading_metadata_as_executions(delivery):
    client, store, spec = delivery
    ids = set()
    for index in range(3):
        item = replace(spec, business_id=f"fixture-{index}")
        store.claim(item)
        ids.add(item.action_id)
    client.hset("mako:delivery:v1:source:reminder", "fixture", "revision")
    cursor, seen = "0:0", set()
    for _ in range(100):
        page = listing.list_delivery_page(client, cursor, limit=2)
        assert len(page.entries) <= 2
        assert all(entry.state == "queued" for entry in page.entries)
        seen.update(entry.action_id for entry in page.entries)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert cursor is None and seen == ids


def test_oversized_scan_batch_is_not_dropped_or_fully_inspected(monkeypatch):
    keys = [f"mako:delivery:v1:{index:064x}" for index in range(25)]
    client = Mock(scan=Mock(return_value=(0, list(reversed(keys)))))
    inspect = Mock(return_value=SimpleNamespace(state="unknown", spec=None))
    monkeypatch.setattr(listing, "DeliveryStore", lambda _: SimpleNamespace(inspect=inspect))
    cursor, seen = "0:0", []
    for expected_count in (10, 10, 5):
        before = inspect.call_count
        page = listing.list_delivery_page(client, cursor)
        assert inspect.call_count - before == expected_count
        seen.extend(entry.action_id for entry in page.entries)
        cursor = page.next_cursor
    assert cursor is None
    assert seen == [key.rsplit(":", 1)[1] for key in keys]


def test_empty_scan_page_keeps_continuation_and_bad_record_remains_visible(monkeypatch):
    key = "mako:delivery:v1:" + "a" * 64
    client = Mock(scan=Mock(side_effect=[(23, []), (0, [key])]))
    inspect = Mock(side_effect=DeliveryUnavailable)
    monkeypatch.setattr(listing, "DeliveryStore", lambda _: SimpleNamespace(inspect=inspect))
    page = listing.list_delivery_page(client)
    assert not page.entries and page.next_cursor == "23:0"
    page = listing.list_delivery_page(client, page.next_cursor)
    assert page.entries[0].state == "unavailable" and page.next_cursor is None
    client.delete.assert_not_called()


@pytest.mark.parametrize("client", [None, Mock(scan=Mock(side_effect=ConnectionError))])
def test_outage_is_not_an_empty_complete_list(client):
    with pytest.raises(DeliveryUnavailable):
        listing.list_delivery_page(client)


@pytest.mark.asyncio
async def test_owner_list_route_returns_next_cursor_when_autonomy_disabled(monkeypatch):
    from test.autonomy.owner_loader import load_owner

    owner = load_owner()
    reader = Mock(return_value=listing.DeliveryPage((), "23:0"))
    feedback = AsyncMock()
    monkeypatch.setitem(owner.process_delivery_command.__globals__, "list_delivery_page", reader)
    monkeypatch.setitem(owner.process_delivery_command.__globals__, "send_to_event", feedback)
    client = object()
    ctx = SimpleNamespace(settings=SimpleNamespace(autonomy_owner_id=99),
        repository=SimpleNamespace(redis_client=client), policy=SimpleNamespace(is_enabled=lambda: False))
    event = Mock(spec=owner.PrivateMessageEvent, user_id=99)
    event.get_plaintext.return_value = "发送列表"
    assert await owner.autonomy_rule(ctx, event)
    assert await owner.process_owner_private(ctx, Mock(), Mock(), event, "发送列表")
    reader.assert_called_once_with(client, "0:0")
    assert "发送列表 23:0" in feedback.call_args.args[2]
    assert "本轮扫描结束" not in feedback.call_args.args[2]
