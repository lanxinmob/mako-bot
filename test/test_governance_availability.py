from __future__ import annotations

from src.services.governance import GovernanceService


class FakeStorage:
    def __init__(self, redis) -> None:
        self.redis = redis

    def is_user_blacklisted(self, _user_id: int) -> bool:
        return False

    def is_group_blacklisted(self, _group_id: int) -> bool:
        return False


def test_required_durable_storage_fails_closed() -> None:
    governance = GovernanceService(storage=FakeStorage(None))
    governance.settings.redis_required = True

    decision = governance.can_chat(1, 2)
    assert decision.allowed is False
    assert decision.reason == "durable storage is unavailable"


def test_development_memory_fallback_is_explicitly_allowed() -> None:
    governance = GovernanceService(storage=FakeStorage(None))
    governance.settings.redis_required = False

    assert governance.can_chat(1, 2).allowed is True
