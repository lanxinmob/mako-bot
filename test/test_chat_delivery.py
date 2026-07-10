from __future__ import annotations

from src.plugins.chat_delivery import render_group_text


def test_render_group_text_prefers_longest_display_name() -> None:
    message = render_group_text("小明同学你好", {"小明": 1, "小明同学": 2})
    assert message[0].type == "at"
    assert message[0].data["qq"] == "2"
    assert "".join(str(segment.data.get("text", "")) for segment in message[1:]) == "你好"


def test_render_group_text_without_member_name_is_plain_text() -> None:
    message = render_group_text("普通回复", {})
    assert all(segment.type == "text" for segment in message)
    assert str(message) == "普通回复"

