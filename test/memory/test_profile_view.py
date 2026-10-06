from unittest.mock import Mock

import pytest

from src.services.memory.profile_view import ProfileViewService, parse_profile_command


def profile(index, nickname=None, text="合成档案正文"):
    return {"user_id": index, "nickname": nickname or f"测试{index}",
            "profile_text": text, "last_updated": "2026-10-07T12:00:00"}


def test_listing_limits_names_without_exposing_profile_bodies():
    storage = Mock()
    storage.list_profiles.return_value = [profile(i) for i in range(8, 0, -1)]
    text = ProfileViewService(storage).render("", user_id=7, owner_id=7)
    assert "8 人" in text
    for i in range(8, 3, -1):
        assert f"{i} · 测试{i}" in text
    assert "3 · 测试3" not in text and "合成档案正文" not in text
    storage.get_profile.assert_not_called()
    storage.list_profiles.return_value = []
    assert "0 人" in ProfileViewService(storage).render("", user_id=7, owner_id=7)


def test_id_lookup_returns_full_text_without_scanning_every_profile():
    storage = Mock()
    body = "完整档案\n" * 1500
    storage.get_profile.return_value = profile(42, text=body)
    result = ProfileViewService(storage).render("42", user_id=7, owner_id=7)
    assert result.endswith(body)
    storage.get_profile.assert_called_once_with(42)
    storage.list_profiles.assert_not_called()
    storage.get_profile.return_value = None
    assert "检查一下 ID" in ProfileViewService(storage).render("43", user_id=7, owner_id=7)


def test_name_lookup_is_exact_and_duplicate_names_require_an_id():
    storage = Mock()
    storage.list_profiles.return_value = [profile(1, "Alice"), profile(2, "Alice Zhang")]
    view = ProfileViewService(storage)
    assert "1 · Alice" in view.render("alice", user_id=7, owner_id=7)
    assert "没找到" in view.render("Ali", user_id=7, owner_id=7)
    storage.list_profiles.return_value.append(profile(3, "ALICE"))
    text = view.render("Alice", user_id=7, owner_id=7)
    assert "重名" in text and "1 · Alice" in text and "3 · ALICE" in text
    assert "合成档案正文" not in text


@pytest.mark.parametrize("caller,owner", [(8, 7), (7, None), (7, 0), (7, "7"), (1, True)])
def test_unauthorized_callers_never_read_storage(caller, owner):
    storage = Mock()
    with pytest.raises(PermissionError):
        ProfileViewService(storage).render("42", user_id=caller, owner_id=owner)
    assert not storage.mock_calls


@pytest.mark.parametrize("text,argument", [
    ("人物档案", ""), ("人物档案 42", "42"), ("茉子，人物档案 Alice Zhang", "Alice Zhang"),
    ("/人物档案 小明", "小明"), ("可塑性记忆 42", "42"), ("/memory 42", "42"),
])
def test_explicit_commands_and_old_aliases(text, argument):
    assert parse_profile_command(text) == argument


@pytest.mark.parametrize("text", ["帮我看人物档案", "人物档案是谁写的", "人物档案\n42", "人物档案 " + "a" * 101])
def test_unrelated_messages_are_not_claimed(text):
    assert parse_profile_command(text) is None
