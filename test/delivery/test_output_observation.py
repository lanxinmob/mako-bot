from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from nonebot.adapters.onebot.v11 import Message, MessageSegment

from src.services.delivery import dispatcher, observation
from src.services.chat.pipeline.participation import GroupParticipation
from src.services.chat.group.models import GroupEvent


@pytest.fixture
def participation(monkeypatch):
    service = GroupParticipation()
    monkeypatch.setattr(observation, "_observer", service.observe_output)
    monkeypatch.setattr(dispatcher, "_configured", True)
    monkeypatch.setattr(dispatcher, "outbound", dispatcher.OutboundDispatcher(spacing=0))
    return service


@pytest.mark.asyncio
async def test_reminder_records_text_once_without_lease(participation):
    bot = SimpleNamespace(self_id="9", send_group_msg=AsyncMock(return_value={"message_id": 12}))
    message = MessageSegment.text("提醒喝水") + MessageSegment.image("https://example.org/private.png")
    assert await dispatcher.send_to_group(bot, 1, message, category="reminder")
    observation.observe_group_output("9", 1, {"message_id": 12}, message, "reminder")
    snapshot = participation.service("9").snapshot("1")
    assert len(snapshot.events) == 1
    assert snapshot.events[0].text == "提醒喝水[图片]"
    assert snapshot.events[0].message_type == "text+image"
    assert snapshot.events[0].kind == "reminder"
    assert snapshot.lease_user_id is None
    assert not participation.service("9").snapshot("2").events
    assert not participation.service("10").snapshot("1").events


@pytest.mark.asyncio
@pytest.mark.parametrize("result", [False, None, {}])
async def test_missing_ack_id_never_fabricates_context(participation, result):
    bot = SimpleNamespace(self_id="9", send_group_msg=AsyncMock(return_value=result))
    assert not await dispatcher.send_to_group(bot, 1, Message("hello"), category="reminder")
    assert not participation.service("9").snapshot("1").events


@pytest.mark.asyncio
@pytest.mark.parametrize("result", [None, {}, {"message_id": None}, False])
async def test_unconfirmed_event_notice_keeps_failure_suppression(participation, result):
    matcher = SimpleNamespace(send=AsyncMock(return_value=result))
    event = SimpleNamespace(self_id="9", group_id=1, user_id=2)
    assert not await dispatcher.send_notice(matcher, event, "notice", notice_key="test")
    matcher.send.assert_awaited_once()
    assert not participation.service("9").snapshot("1").events
    matcher.send.return_value = {"message_id": 123}
    # Failure suppression also prevents outage spam; it is not a delivery ACK.
    assert not await dispatcher.send_notice(matcher, event, "notice", notice_key="test")
    matcher.send.assert_awaited_once()
    assert await dispatcher.send_notice(matcher, event, "other notice", notice_key="other")
    assert matcher.send.await_count == 2


@pytest.mark.asyncio
async def test_event_group_only_and_observer_error_does_not_retry(participation, monkeypatch):
    matcher = SimpleNamespace(send=AsyncMock(return_value={"message_id": 7}))
    event = SimpleNamespace(self_id="9", group_id=1, user_id=2)
    assert await dispatcher.send_to_event(matcher, event, Message("done"))
    assert participation.service("9").snapshot("1").events[0].text == "done"
    private = SimpleNamespace(self_id="9", user_id=2)
    assert await dispatcher.send_to_event(matcher, private, Message("private"))
    assert len(participation.service("9").snapshot("1").events) == 1

    def broken(_):
        raise RuntimeError("observer failed")

    monkeypatch.setattr(observation, "_observer", broken)
    assert await dispatcher.send_to_event(matcher, event, Message("sent"))
    assert matcher.send.await_count == 3


def test_segment_metadata_is_bounded_and_has_no_media_url(participation):
    message = (MessageSegment.reply(4) + MessageSegment.at("all")
               + MessageSegment.record("https://example.org/private.wav"))
    observation.observe_group_output("9", 1, {"message_id": 5}, message, "command")
    event = participation.service("9").snapshot("1").events[0]
    assert event.text == "[语音]"
    assert event.message_type == "record"
    assert event.mentions == ("all",)
    assert event.reply_to_message_id == "4"


@pytest.mark.parametrize("already_sent", [False, True])
def test_passive_output_preserves_conversation_owner(participation, already_sent):
    service = participation.service("9")
    service.debounce_seconds = 0
    service.observe(GroupEvent("1", "human", "2", "mako hello", direct_call=True))
    candidate = service.begin_candidate(service.select_decision(service.snapshot("1")))
    assert candidate is not None
    if already_sent:
        assert service.mark_sent(candidate)
    before = service.snapshot("1")
    state = service.window.groups["1"]
    pending_until = state.pending_until
    observation.observe_group_output("9", 1, {"message_id": 8}, Message("reminder"), "reminder")
    after = service.snapshot("1")
    assert after.revision > before.revision
    assert after.generation == before.generation
    assert (after.lease_user_id, after.lease_until) == (before.lease_user_id, before.lease_until)
    assert state.pending_until == pending_until
    assert after.trigger.message_id == "human"
    if not already_sent:
        assert state.candidate == candidate
        assert not service.candidate_is_current(candidate)
        refreshed = service.revalidate_candidate(candidate, service.select_decision(after))
        assert refreshed is not None
        assert refreshed.expires_at == candidate.expires_at
    else:
        assert service.select_decision(after).reason == "already_sent"


def test_passive_output_alone_never_requests_reply(participation):
    observation.observe_group_output("9", 1, {"message_id": 8}, Message("news"), "news")
    service = participation.service("9")
    assert service.snapshot("1").trigger is None
    assert service.select_decision(service.snapshot("1")).action == "ignore"
