from __future__ import annotations

import unittest

from src.services.chat_policy import ChatAddress, compact_text, should_reply


class ChatAddressTest(unittest.TestCase):
    def test_group_session_keeps_existing_shared_semantics(self) -> None:
        address = ChatAddress(message_type="group", user_id=7, group_id=42)
        self.assertEqual(address.session_id, "group_42")

    def test_private_session_is_per_user(self) -> None:
        address = ChatAddress(message_type="private", user_id=7)
        self.assertEqual(address.session_id, "private_7")


class ReplyAdmissionTest(unittest.TestCase):
    def test_explicit_mention_always_replies(self) -> None:
        self.assertTrue(should_reply("hello", is_to_me=True, random_chance=0, sample=1))

    def test_name_mention_is_case_insensitive_for_mako(self) -> None:
        self.assertTrue(should_reply("MAKO 在吗", is_to_me=False, random_chance=0, sample=1))

    def test_random_reply_uses_configured_probability(self) -> None:
        self.assertTrue(should_reply("路过", is_to_me=False, random_chance=0.2, sample=0.1))
        self.assertFalse(should_reply("路过", is_to_me=False, random_chance=0.2, sample=0.3))

    def test_probability_is_clamped(self) -> None:
        self.assertFalse(should_reply("x", is_to_me=False, random_chance=-1, sample=0))
        self.assertTrue(should_reply("x", is_to_me=False, random_chance=2, sample=0.999))


class CompactTextTest(unittest.TestCase):
    def test_compacts_whitespace_and_truncates(self) -> None:
        self.assertEqual(compact_text(" a\n b ", 20), "a b")
        self.assertEqual(compact_text("abcdef", 3), "abc...")


if __name__ == "__main__":
    unittest.main()

