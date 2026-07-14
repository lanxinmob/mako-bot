from __future__ import annotations

import unittest

from src.core.config import Settings
from src.services.chat_policy import (
    ChatAddress,
    compact_text,
    remaining_reply_delay,
    select_reply_plan,
    should_record_message,
    should_reply,
    truncate_reply,
)


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


class ReplyPlanTest(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(_env_file=None, REDIS_REQUIRED=False, LLM_REQUIRED=False)

    def test_simple_greeting_is_micro_with_configured_limit(self) -> None:
        plan = select_reply_plan(
            "早安",
            message_type="private",
            directed=True,
            settings=self.settings,
        )
        self.assertEqual(plan.mode, "micro")
        self.assertEqual(plan.max_chars, 168)
        self.assertEqual(plan.max_tokens, 384)

    def test_complex_or_emotional_message_can_expand(self) -> None:
        for text in ("请详细解释一下为什么", "今天真的好累"):
            plan = select_reply_plan(
                text,
                message_type="private",
                directed=True,
                settings=self.settings,
            )
            self.assertEqual(plan.mode, "deep")
            self.assertEqual(plan.max_chars, 2560)

    def test_fast_exchange_forces_short_mode(self) -> None:
        plan = select_reply_plan(
            "请详细解释这个问题",
            message_type="group",
            directed=True,
            fast_exchange=True,
            settings=self.settings,
        )
        self.assertEqual(plan.mode, "short")
        self.assertEqual(plan.max_chars, 400)
        self.assertEqual(plan.social_state, "rapid_exchange")

    def test_delay_counts_generation_time(self) -> None:
        plan = select_reply_plan(
            "早安",
            message_type="private",
            directed=True,
            settings=self.settings,
        )
        self.assertAlmostEqual(remaining_reply_delay(plan, 0.3, sample=0.0), 0.5)
        self.assertEqual(remaining_reply_delay(plan, 3.0, sample=1.0), 0.0)

    def test_truncation_respects_hard_limit_and_sentence_boundary(self) -> None:
        text = "第一句已经说完。第二句会超过限制而被截断。"
        result = truncate_reply(text, 12)
        self.assertLessEqual(len(result), 12)
        self.assertTrue(result.endswith("…"))


class RecordingPolicyTest(unittest.TestCase):
    def test_private_messages_are_recorded(self) -> None:
        self.assertTrue(
            should_record_message(
                message_type="private",
                directed=False,
                will_reply=False,
                record_undirected_group_messages=False,
            )
        )

    def test_ignored_group_messages_are_private_by_default(self) -> None:
        self.assertFalse(
            should_record_message(
                message_type="group",
                directed=False,
                will_reply=False,
                record_undirected_group_messages=False,
            )
        )

    def test_group_observation_requires_explicit_opt_in(self) -> None:
        self.assertTrue(
            should_record_message(
                message_type="group",
                directed=False,
                will_reply=False,
                record_undirected_group_messages=True,
            )
        )


if __name__ == "__main__":
    unittest.main()
