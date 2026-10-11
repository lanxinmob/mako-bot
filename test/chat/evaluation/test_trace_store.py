import asyncio
import json
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from src.services.chat.observability.store import RhythmTraceStore
from src.services.chat.observability import events


def test_capacity_ttl_aliases_and_late_updates_do_not_recreate():
    now = [10.0]
    store = RhythmTraceStore(clock=lambda: now[0], capacity=2, retention_seconds=30)
    store.observe('private-bot', 'private-group', 'a')
    first = store.snapshot()['data']['items'][0]
    now[0] = 11
    store.observe('private-bot', 'private-group', 'b')
    store.observe('other-bot', 'private-group', 'b')
    assert len(store.rows) == 2
    store.update('private-bot', 'private-group', 'a', send_state='confirmed')
    assert len(store.rows) == 2
    items = store.snapshot()['data']['items']
    assert items[0]['group_alias'] != items[1]['group_alias']
    assert 'private-group' not in json.dumps(items)
    now[0] = 40
    store.update('private-bot', 'private-group', 'b', stage='generating')
    now[0] = 41
    assert store.snapshot()['data']['items'] == []
    store.update('private-bot', 'private-group', 'b', send_state='confirmed')
    assert not store.rows
    assert RhythmTraceStore().snapshot()['data']['items'] == []


def test_decision_delivery_and_late_cancel_are_separate():
    store = RhythmTraceStore()
    store.observe('1', '2', '3')
    store.update('1', '2', '3', action='reply', reason_code='direct_call', stage='generating')
    row = store.snapshot()['data']['items'][0]
    assert row['send_state'] == 'not_started'
    store.update('1', '2', '3', send_state='in_flight')
    store.update('1', '2', '3', stage='canceled', outcome_reason_code='closure')
    row = store.snapshot()['data']['items'][0]
    assert row['late_cancel'] and row['send_state'] == 'unknown'
    store.update('1', '2', '3', send_state='confirmed', stage='finished')
    row = store.snapshot()['data']['items'][0]
    assert row['send_state'] == 'confirmed' and row['stage'] == 'canceled'
    with pytest.raises(ValueError):
        store.update('1', '2', '3', text='private content')
    with pytest.raises(ValueError):
        store.snapshot(201)


def test_late_generation_preserves_cancel_until_a_new_admitted_generation(monkeypatch):
    store = RhythmTraceStore()
    monkeypatch.setattr(events, 'store', store)
    incoming = NS(bot_id='1', message_id='3', work_kind='chat', address=NS(group_id=2))
    store.observe('1', '2', '3')
    events.phase(incoming, 'generating')
    store.update('1', '2', '3', stage='canceled', outcome_reason_code='answered')
    events.phase(incoming, 'candidate')
    events.phase(incoming, 'canceled', 'guard_rejected')
    row = store.snapshot()['data']['items'][0]
    assert row['stage'] == 'canceled' and row['outcome_reason_code'] == 'answered'
    events.phase(incoming, 'generating')
    row = store.snapshot()['data']['items'][0]
    assert row['stage'] == 'generating' and row['outcome_reason_code'] is None


@pytest.mark.asyncio
async def test_trace_failure_cannot_stop_or_repeat_transport(monkeypatch):
    monkeypatch.setattr(events, 'store', NS(update=lambda *a, **k: (_ for _ in ()).throw(RuntimeError())))
    matcher = NS(send=AsyncMock(return_value={'message_id': 'ack'}))
    result = await events.tracked_send(matcher, 'synthetic', NS(self_id=1), NS(group_id=2, message_id=3), 'chat')
    assert result == {'message_id': 'ack'}
    matcher.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_unknown_cancellation_does_not_become_failure(monkeypatch):
    store = RhythmTraceStore()
    monkeypatch.setattr(events, 'store', store)
    store.observe('1', '2', '3')
    matcher = NS(send=AsyncMock(side_effect=asyncio.CancelledError()))
    with pytest.raises(asyncio.CancelledError):
        await events.tracked_send(matcher, 'synthetic', NS(self_id=1), NS(group_id=2, message_id=3), 'chat')
    assert store.snapshot()['data']['items'][0]['send_state'] == 'unknown'
    matcher.send.assert_awaited_once()
