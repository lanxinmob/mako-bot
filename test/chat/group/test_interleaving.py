"""Synthetic group isolation and real asyncio cancellation interleavings."""

import asyncio
from dataclasses import replace

import pytest

from .fixtures import candidate_for, event, make_service


def test_same_ids_in_two_groups_keep_candidates_quotes_and_leases_separate():
    service, _ = make_service()
    first = candidate_for(service)
    other = candidate_for(service, replace(first.trigger, group_id="other"))
    first_snapshot = service.snapshot("g")
    service.observe(replace(event("2", text="不用回了"), group_id="other"))
    assert service.snapshot("g") == first_snapshot
    assert service.candidate_is_current(first)
    assert not service.candidate_is_current(other)
    assert service.mark_sent(first)
    service.observe_outbound(event("bot1", user_id="42"), lease_user_id="7")
    quoted = replace(event("3", reply_to_message_id="bot1"), group_id="other")
    assert service.select_decision(service.observe(quoted)).reason == "reply_to_other"
    assert service.select_decision(service.observe(event("4"))).reason == "followup"
    assert service.snapshot("other").lease_user_id is None


def test_cancelled_old_generator_finally_cannot_release_successor():
    async def scenario():
        service, _ = make_service()
        old = candidate_for(service)
        entered = asyncio.Event()
        cleanup_results = []

        async def generating():
            try:
                entered.set()
                await asyncio.Event().wait()
            finally:
                cleanup_results.append(service.cancel_candidate(old))

        task = asyncio.create_task(generating())
        await entered.wait()
        new = candidate_for(service, event("2", user_id="8", text="茉子，新的请求"))
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cleanup_results == [False]
        assert service.candidate_is_current(new)
        assert not service.mark_sent(old)
        assert service.mark_sent(new)

    asyncio.run(scenario())


def test_cancel_current_owner_releases_slot_without_renewing_deadline():
    service, clock = make_service()
    old = candidate_for(service)
    clock.advance(2)
    assert service.cancel_candidate(old)
    assert not service.cancel_candidate(old)
    new = service.begin_candidate(service.select_decision(service.snapshot("g")))
    assert new is not None and new.generation > old.generation
    assert new.expires_at == old.expires_at
    assert not service.cancel_candidate(old)
    assert service.candidate_is_current(new)


def test_other_group_event_does_not_stale_pending_classifier():
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        async def classifier(snapshot):
            entered.set()
            await release.wait()
            return {"action": "reply", "target_message_id": snapshot.trigger.message_id}

        service, _ = make_service(classifier=classifier)
        snapshot = service.observe(event(text="茉子，帮我看看"))
        task = asyncio.create_task(service.decide(snapshot))
        await entered.wait()
        other = candidate_for(service, replace(event(text="茉子，另一个群"), group_id="other"))
        release.set()
        decision = await task
        assert decision.action == "reply" and service.decision_is_current(decision)
        assert service.begin_candidate(decision) is not None
        assert service.candidate_is_current(other)

    asyncio.run(scenario())


@pytest.mark.parametrize("incoming", [
    event(text="我觉得茉子说得不错"),
    event(text="mako今天说过了"),
    event(reply_to_user_id="8"),
    event(mentions=("8",)),
    event(text="不用回了", direct_call=True),
    event(text="茉子，你怎么看", is_bot=True),
])
def test_hard_exclusions_never_call_optional_classifier(incoming):
    calls = []

    async def classifier(snapshot):
        calls.append(snapshot)
        return {"action": "reply", "target_message_id": snapshot.trigger.message_id}

    service, _ = make_service(classifier=classifier)
    assert asyncio.run(service.decide(service.observe(incoming))).action == "ignore"
    assert calls == []


def test_duplicate_event_does_not_extend_pending_or_retention_deadline():
    service, clock = make_service()
    incoming = event(text="茉子，帮我看看")
    snapshot = service.observe(incoming)
    candidate = service.begin_candidate(service.select_decision(snapshot))
    clock.advance(24)
    assert service.observe(incoming) == snapshot
    clock.advance(1)
    assert not service.candidate_is_current(candidate)
    clock.advance(575)
    assert service.snapshot("g").events == ()


def test_same_user_supplements_reach_original_wait_bound():
    service, clock = make_service(debounce_seconds=1, max_wait_seconds=2)
    first = service.select_decision(service.observe(event(text="茉子，帮我看看")))
    for index in range(1, 5):
        clock.advance(0.5)
        decision = service.select_decision(service.observe(event(str(index + 1), text="再补充一点")))
    assert not service.decision_is_current(first)
    assert decision.action == "reply" and decision.target_message_id == "1"


def test_public_options_still_update_composed_owners():
    service, clock = make_service()
    service.bot_names = ("助手",)
    service.max_events = 2
    service.candidate_ttl_seconds = 3
    service.lease_seconds = 4
    service.debounce_seconds = 1
    snapshot = service.observe(event(text="助手，请看这个"))
    assert service.select_decision(snapshot).wait_seconds == 1
    service.debounce_seconds = 0
    candidate = service.begin_candidate(service.select_decision(snapshot))
    assert candidate.expires_at == clock() + 3
    assert service.mark_sent(candidate)
    assert service.snapshot("g").lease_until == clock() + 4
    service.observe(event("2"))
    service.observe(event("3"))
    assert len(service.snapshot("g").events) == 2
