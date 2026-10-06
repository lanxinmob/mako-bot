from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import pytest

from src.services.chat.group import render_snapshot
from .fixtures import candidate_for, event, make_service


def test_observe_required_duplicate_idempotence_and_one_candidate_slot():
    service, _ = make_service()
    assert service.select_decision(service.snapshot("g")).action == "ignore"
    incoming = event(text="茉子？")
    snapshot = service.observe(incoming)
    assert service.observe(incoming) == snapshot
    decision = service.select_decision(snapshot)
    candidate = service.begin_candidate(decision)
    assert candidate.trigger == incoming
    assert service.begin_candidate(decision) is None
    assert service.mark_sent(candidate)
    assert not service.candidate_is_current(candidate)
    assert service.select_decision(service.observe(incoming)).reason == "already_sent"


def test_direct_question_survives_busy_group_with_bounded_wait():
    service, clock = make_service(debounce_seconds=1, max_wait_seconds=2.5)
    snapshot = service.observe(event(text="茉子，请帮我看看"))
    first = service.select_decision(snapshot)
    assert first.action == "wait"
    for i in range(1, 6):
        clock.advance(0.5)
        snapshot = service.observe(event(str(i + 1), user_id="8", text="无关讨论"))
        decision = service.select_decision(snapshot)
    assert not service.decision_is_current(first)
    assert decision.action == "reply" and decision.target_message_id == "1"
    candidate = service.begin_candidate(decision)
    assert candidate.trigger.message_id == "1"
    assert candidate.expires_at == 125


def test_changed_context_candidate_requires_review_and_preserves_deadline():
    service, clock = make_service()
    original = candidate_for(service)
    clock.advance(1)
    snapshot = service.observe(event("2", user_id="8", text="我的午饭到了"))
    assert not service.candidate_is_current(original)
    decision = service.select_decision(snapshot)
    assert service.begin_candidate(decision) is None  # no second generation slot
    refreshed = service.revalidate_candidate(original, decision)
    assert refreshed and service.candidate_is_current(refreshed)
    assert refreshed.expires_at == original.expires_at
    assert refreshed.trigger == original.trigger
    assert not service.cancel_candidate(original)  # stale worker cannot cancel new token
    assert service.mark_sent(refreshed)


@pytest.mark.parametrize("closing", [
    event("2", text="解决了谢谢"),
    event("2", user_id="8", text="答案是这个", reply_to_message_id="1"),
])
def test_closure_or_answer_invalidates_sticky_target(closing):
    service, _ = make_service()
    candidate = candidate_for(service)
    snapshot = service.observe(closing)
    assert snapshot.trigger.message_id == "2"
    assert not service.candidate_is_current(candidate)
    assert service.revalidate_candidate(candidate, service.select_decision(snapshot)) is None


def test_new_direct_question_replaces_old_candidate_and_expiry_releases_slot():
    service, clock = make_service()
    first = candidate_for(service)
    second = candidate_for(service, event("2", user_id="8", text="茉子，另一件事"))
    assert not service.candidate_is_current(first)
    assert not service.cancel_candidate(first)
    clock.advance(25)
    assert not service.candidate_is_current(second)
    third = candidate_for(service, event("3", text="茉子，请看这件事"))
    assert service.candidate_is_current(third)


def test_outbound_identity_reply_resolution_and_followup_lease():
    service, clock = make_service(lease_seconds=30)
    candidate = candidate_for(service)
    assert service.mark_sent(candidate)
    sent = event("bot1", user_id="42", text="这是我的回答", reply_to_message_id="1",
                 reply_to_user_id="7")
    snapshot = service.observe_outbound(sent)
    assert snapshot.lease_user_id == "7" and snapshot.events[-1].is_bot
    clock.advance(1)
    assert service.observe_outbound(sent).lease_until == snapshot.lease_until
    followup = service.select_decision(service.observe(event("2", text="那还有一种呢？")))
    assert followup.reason == "followup"
    quoted = service.select_decision(service.observe(event("3", text="这个呢？",
                                                         reply_to_message_id="bot1")))
    assert quoted.reason == "direct_call"
    with pytest.raises(ValueError):
        service.observe_outbound(event("bad"))


@pytest.mark.parametrize("interruption", [
    event("2", user_id="8"), event("2", text="不用回了"),
    event("2", reply_to_user_id="8"),
])
def test_interruption_ends_followup_lease(interruption):
    service, _ = make_service()
    service.observe_outbound(event("bot1", user_id="42"), lease_user_id="7")
    service.observe(interruption)
    decision = service.select_decision(service.observe(event("3", text="还有呢")))
    assert decision.reason == "ambient"


def test_lease_expires_and_tool_outbound_does_not_open_one():
    service, clock = make_service(lease_seconds=3)
    service.observe_outbound(event("bot1", user_id="42"), lease_user_id="7")
    clock.advance(3)
    assert service.select_decision(service.observe(event("2"))).reason == "ambient"
    snapshot = service.observe_outbound(event("bot2", user_id="42", kind="tool"),
                                        lease_user_id="7")
    assert snapshot.lease_user_id is None
