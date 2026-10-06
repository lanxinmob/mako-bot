from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import pytest

from src.services.chat.group import render_snapshot
from .fixtures import candidate_for, event, make_service


def test_known_bot_ids_normalized_and_event_identity_retained():
    service, _ = make_service()
    incoming = event(user_id=99, message_id=5, mentions=[42], timestamp=-100000,
                     nickname="机器人", message_type="image")
    snapshot = service.observe(incoming)
    assert snapshot.events == (incoming,)
    assert incoming.message_id == "5" and incoming.mentions == ("42",)
    assert service.select_decision(snapshot).reason == "known_bot"


def test_ttl_is_local_receipt_not_remote_time_and_buffer_is_capped():
    service, clock = make_service()
    for i in range(70):
        service.observe(event(str(i), timestamp=10**12, text="x" * 5000))
    snapshot = service.snapshot("g")
    assert len(snapshot.events) == 60
    assert snapshot.events[0].message_id == "10"
    assert len(snapshot.events[-1].text) == 2000
    clock.advance(599)
    service.observe(event("next"))
    clock.advance(1)
    assert [e.message_id for e in service.snapshot("g").events] == ["next"]
    clock.advance(600)
    assert service.snapshot("g").events == ()


def test_group_cleanup_bounded_and_tokens_do_not_reappear_after_eviction():
    service, clock = make_service(max_groups=3, cleanup_budget=1)
    original = candidate_for(service)
    revision = original.revision
    for group_id in ("g2", "g3", "g4"):
        service.observe(replace(event(), group_id=group_id))
    assert service.group_count == 3
    assert not service.candidate_is_current(original)
    current = service.observe(event(text="茉子？"))
    assert current.revision > revision and current.generation > original.generation
    clock.advance(600)
    assert service.cleanup() == 1
    assert service.group_count == 2


def test_snapshot_render_is_bounded_and_keeps_metadata_and_latest_events():
    service, _ = make_service()
    service.observe(event("1", text="first"))
    snapshot = service.observe(event("2", text="line1\nline2", reply_to_message_id="1",
                                     reply_to_user_id="7", mentions=("8",)))
    lines = render_snapshot(snapshot).splitlines()
    assert len(lines) == 2
    latest = json.loads(lines[-1])
    assert latest["text"] == "line1\nline2"
    assert latest["reply_to_message_id"] == "1" and latest["mentions"] == ["8"]
    assert render_snapshot(snapshot, len(lines[-1])) == lines[-1]
    assert len(snapshot.render(20)) <= 20
    assert snapshot.render(0) == ""
