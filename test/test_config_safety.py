from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.core.config import Settings


def test_dashboard_token_rejects_short_secrets() -> None:
    with pytest.raises(ValidationError, match="at least 32 characters"):
        Settings(DASHBOARD_TOKEN="too-short")


def test_autonomy_requires_owner_and_target() -> None:
    with pytest.raises(ValidationError, match="AUTONOMY_OWNER_ID"):
        Settings(AUTONOMY_ENABLED=True)

    with pytest.raises(ValidationError, match="At least one"):
        Settings(AUTONOMY_ENABLED=True, AUTONOMY_OWNER_ID=123)


def test_safe_optional_features_are_disabled_by_default() -> None:
    settings = Settings()
    assert settings.autonomy_enabled is False
    assert settings.proactive_enabled is False
    assert settings.record_undirected_group_messages is False
    assert settings.chat_rhythm_enabled is True
    assert settings.chat_reply_max_chars_micro == 168
    assert settings.chat_reply_max_chars_short == 400
    assert settings.chat_reply_max_chars_normal == 1120
    assert settings.chat_reply_max_chars_deep == 2560
