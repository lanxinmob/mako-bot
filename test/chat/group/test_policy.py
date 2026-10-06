from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import pytest

from src.services.chat.group import render_snapshot
from .fixtures import candidate_for, event, make_service


@pytest.mark.parametrize("text,kwargs,action,reason", [
    ("茉子，怎么看", {}, "reply", "direct_call"),
    ("mako你怎么看", {}, "reply", "direct_call"),
    ("我觉得茉子挺好的", {}, "ignore", "name_mention"),
    ("mako今天说过了", {}, "ignore", "name_mention"),
    ("谁知道怎么办？", {}, "ignore", "ambient"),
    ("你怎么看", {"mentions": (42,)}, "reply", "direct_call"),
    ("你怎么看", {"reply_to_user_id": 42}, "reply", "direct_call"),
    ("怎么办", {"reply_to_user_id": 8}, "ignore", "reply_to_other"),
    ("怎么办", {"reply_to_message_id": "unknown"}, "ignore", "reply_to_other"),
    ("怎么办", {"mentions": (8,)}, "ignore", "reply_to_other"),
    ("怎么办", {"reply_to_user_id": 8, "mentions": (42,)}, "reply", "direct_call"),
    ("茉子谢谢", {}, "ignore", "closure"),
    ("解决了，谢谢！", {"direct_call": True}, "ignore", "closure"),
    ("不用回了", {"mentions": (42,)}, "ignore", "closure"),
    ("茉子你怎么看", {"is_bot": True}, "ignore", "known_bot"),
    ("", {}, "ignore", "empty"),
])
def test_cheap_gate(text, kwargs, action, reason):
    service, _ = make_service()
    decision = service.select_decision(service.observe(event(text=text, **kwargs)))
    assert (decision.action, decision.reason) == (action, reason)


@pytest.mark.parametrize("kind", ["tool", "reminder"])
def test_explicit_workflows_bypass_classifier_and_disposable_slot(kind):
    async def classifier(snapshot):
        raise AssertionError("explicit workflow reached classifier")

    service, _ = make_service(classifier=classifier)
    snapshot = service.observe(event(kind=kind, text="不用回了"))
    decision = asyncio.run(service.decide(snapshot))
    assert decision.action == "reply" and not decision.disposable
    assert service.begin_candidate(decision) is None


@pytest.mark.parametrize("result", [None, [], {"action": []}, {"action": "dance"},
    {"action": "reply", "target_message_id": "missing"},
    {"action": "reply", "target_message_id": True}])
def test_classifier_malformed_or_wrong_target_falls_back(result):
    async def classifier(snapshot):
        return result

    service, _ = make_service(classifier=classifier)
    decision = asyncio.run(service.decide(service.observe(event())))
    assert decision.action == "ignore" and decision.reason == "ambient"


def test_classifier_can_decline_direct_composite_and_followup():
    seen = []

    async def classifier(snapshot):
        seen.append(snapshot.trigger.text)
        return {"action": "ignore"}

    service, _ = make_service(classifier=classifier)
    snapshot = service.observe(event(text="茉子，谢谢你，刚才那件事已经解决了"))
    assert asyncio.run(service.decide(snapshot)).reason == "model_ignore"
    service.observe_outbound(event("bot1", user_id="42"), lease_user_id="7")
    snapshot = service.observe(event("2", text="今天饭真好吃"))
    assert asyncio.run(service.decide(snapshot)).reason == "model_ignore"
    assert len(seen) == 2


def test_classifier_reply_and_wait_deadline_are_bounded():
    async def classifier(snapshot):
        return {"action": "reply", "target_message_id": snapshot.trigger.message_id}

    service, clock = make_service(classifier=classifier, debounce_seconds=1, max_wait_seconds=2)
    snapshot = service.observe(event())
    assert asyncio.run(service.decide(snapshot)).action == "wait"
    clock.advance(2)
    assert asyncio.run(service.decide(snapshot)).action == "reply"

    async def waiting(snapshot):
        return {"action": "wait", "target_message_id": snapshot.trigger.message_id}

    service.classifier = waiting
    assert asyncio.run(service.decide(snapshot)).reason == "wait_expired"


def test_classifier_timeout_failure_and_cancellation():
    async def slow(snapshot):
        await asyncio.Event().wait()

    service, _ = make_service(classifier=slow, classifier_timeout_seconds=0.01)
    assert asyncio.run(service.decide(service.observe(event()))).reason == "ambient"

    async def broken(snapshot):
        raise RuntimeError("provider unavailable")

    service.classifier = broken
    snapshot = service.observe(event("2", text="茉子，帮我解释"))
    assert asyncio.run(service.decide(snapshot)).reason == "direct_call"

    async def cancelled(snapshot):
        raise asyncio.CancelledError()

    service.classifier = cancelled
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(service.decide(snapshot))


def test_classifier_result_rejected_after_new_event_and_old_waiter_is_stale():
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        async def classifier(snapshot):
            entered.set()
            await release.wait()
            return {"action": "reply", "target_message_id": snapshot.trigger.message_id}

        service, _ = make_service(classifier=classifier)
        snapshot = service.observe(event())
        task = asyncio.create_task(service.decide(snapshot))
        await entered.wait()
        service.observe(event("2"))
        release.set()
        assert (await task).reason == "stale_classifier"
        assert service.select_decision(snapshot).reason == "stale_snapshot"

    asyncio.run(scenario())


def test_semantic_ignore_drops_changed_context_candidate():
    async def classifier(snapshot):
        return {"action": "ignore"}

    service, _ = make_service()
    candidate = candidate_for(service)
    service.classifier = classifier
    snapshot = service.observe(event("2", user_id="8", text="这个问题我已经解释好了"))
    decision = asyncio.run(service.decide(snapshot))
    assert decision.action == "ignore"
    assert service.revalidate_candidate(candidate, decision) is None
    assert not service.candidate_is_current(candidate)
