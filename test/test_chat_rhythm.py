from __future__ import annotations

from src.core.config import Settings
from src.services.chat_rhythm import ChatRhythmService


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, key: str):
        return self.values.get(key)

    def set(self, key: str, value: str) -> None:
        self.values[key] = value

    def expire(self, key: str, seconds: int) -> None:
        return None


class FakeStorage:
    def __init__(self, redis=None) -> None:
        self.redis = redis


def make_settings(**overrides) -> Settings:
    values = {
        "REDIS_REQUIRED": False,
        "LLM_REQUIRED": False,
        "KNOWN_BOT_USER_IDS": "99",
        "CHAT_RHYTHM_FAST_TURN_SECONDS": 6,
        "CHAT_RHYTHM_WINDOW_SECONDS": 30,
        "CHAT_RHYTHM_COOLDOWN_SECONDS": 90,
        "CHAT_RHYTHM_MAX_COOLDOWN_SECONDS": 900,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_known_bot_gets_two_replies_then_boundary_and_cooldown() -> None:
    service = ChatRhythmService(FakeStorage(), settings=make_settings())
    session = "group_1"

    first = service.admit(session, message_type="group", sender_id=99, now=0)
    assert first.allowed and not first.boundary
    service.mark_sent(session, sender_id=99, now=1)

    second = service.admit(session, message_type="group", sender_id=99, now=2)
    assert second.allowed and second.force_short and not second.boundary
    service.mark_sent(session, sender_id=99, now=3)

    third = service.admit(session, message_type="group", sender_id=99, now=4)
    assert third.allowed and third.boundary
    service.mark_sent(session, sender_id=99, boundary=True, now=5)

    blocked = service.admit(session, message_type="group", sender_id=99, now=6)
    assert not blocked.allowed
    assert blocked.social_state == "cooldown"


def test_unknown_sender_requires_more_evidence_before_boundary() -> None:
    service = ChatRhythmService(FakeStorage(), settings=make_settings())
    session = "group_2"

    service.admit(session, message_type="group", sender_id=42, now=0)
    service.mark_sent(session, sender_id=42, now=1)
    for incoming, sent in ((2, 3), (4, 5)):
        decision = service.admit(session, message_type="group", sender_id=42, now=incoming)
        assert decision.allowed and not decision.boundary
        service.mark_sent(session, sender_id=42, now=sent)

    boundary = service.admit(session, message_type="group", sender_id=42, now=6)
    assert boundary.boundary
    assert boundary.rapid_turns == 3


def test_human_interruption_clears_active_cooldown() -> None:
    service = ChatRhythmService(FakeStorage(), settings=make_settings())
    session = "group_3"
    service.admit(session, message_type="group", sender_id=99, now=0)
    service.mark_sent(session, sender_id=99, boundary=True, now=1)

    human = service.admit(session, message_type="group", sender_id=7, now=2)
    assert human.allowed
    assert human.social_state == "human_interruption"


def test_cooldown_state_is_shared_through_redis() -> None:
    redis = FakeRedis()
    settings = make_settings()
    first = ChatRhythmService(FakeStorage(redis), settings=settings)
    first.admit("group_4", message_type="group", sender_id=99, now=0)
    first.mark_sent("group_4", sender_id=99, boundary=True, now=1)

    restarted = ChatRhythmService(FakeStorage(redis), settings=settings)
    decision = restarted.admit("group_4", message_type="group", sender_id=99, now=2)
    assert not decision.allowed


def test_repeated_boundaries_increase_cooldown_without_resetting_too_early() -> None:
    service = ChatRhythmService(FakeStorage(), settings=make_settings())
    session = "group_5"
    service.admit(session, message_type="group", sender_id=99, now=0)
    service.mark_sent(session, sender_id=99, boundary=True, now=1)

    # First cooldown ends at 91. Build another fast exchange afterwards.
    service.admit(session, message_type="group", sender_id=99, now=92)
    service.mark_sent(session, sender_id=99, now=93)
    service.admit(session, message_type="group", sender_id=99, now=94)
    service.mark_sent(session, sender_id=99, now=95)
    boundary = service.admit(session, message_type="group", sender_id=99, now=96)
    assert boundary.boundary
    service.mark_sent(session, sender_id=99, boundary=True, now=97)

    # Second cooldown is 270 seconds, so it still blocks at 300.
    assert not service.admit(
        session, message_type="group", sender_id=99, now=300
    ).allowed


def test_private_chat_is_not_subject_to_group_loop_control() -> None:
    service = ChatRhythmService(FakeStorage(), settings=make_settings())
    decision = service.admit("private_99", message_type="private", sender_id=99, now=1)
    assert decision.allowed
    assert not decision.boundary
