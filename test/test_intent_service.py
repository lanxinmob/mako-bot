from __future__ import annotations

import unittest

from src.services.intent import IntentDecision, _dedupe_intents, decide_intents


class IntentServiceTest(unittest.TestCase):
    def test_pure_audio_message_triggers_stt(self) -> None:
        intents = decide_intents(text="", has_image=False, has_audio=True, face_ids=[])
        names = [item.name for item in intents]
        self.assertIn("language.stt", names)

    def test_intent_dedupe_keeps_order(self) -> None:
        raw = [
            IntentDecision(name="search.web", args={"query": "openai"}),
            IntentDecision(name="search.web", args={"query": "openai"}),
            IntentDecision(name="weather.query", args={"text": "上海天气"}),
            IntentDecision(name="weather.query", args={"text": "上海天气"}),
        ]
        deduped = _dedupe_intents(raw)
        self.assertEqual(
            deduped,
            [
                IntentDecision(name="search.web", args={"query": "openai"}),
                IntentDecision(name="weather.query", args={"text": "上海天气"}),
            ],
        )

    def test_explicit_search_phrase_triggers_web_search(self) -> None:
        intents = decide_intents(text="帮我查一下 qwen-vl-plus 最新价格", has_image=False, has_audio=False)
        self.assertIn("search.web", [item.name for item in intents])

    def test_search_variant_phrase_triggers_web_search(self) -> None:
        intents = decide_intents(text="你能查一查具体比分吗", has_image=False, has_audio=False)
        self.assertIn("search.web", [item.name for item in intents])

    def test_score_query_triggers_web_search(self) -> None:
        intents = decide_intents(text="具体比分是多少", has_image=False, has_audio=False)
        self.assertIn("search.web", [item.name for item in intents])

    def test_yesterday_major_result_triggers_web_search(self) -> None:
        intents = decide_intents(text="你知道昨天科隆major的比赛结果吗", has_image=False, has_audio=False)
        self.assertIn("search.web", [item.name for item in intents])

    def test_casual_now_phrase_does_not_trigger_web_search(self) -> None:
        intents = decide_intents(text="我现在有点难过", has_image=False, has_audio=False)
        self.assertNotIn("search.web", [item.name for item in intents])

    def test_user_correction_forces_web_search(self) -> None:
        for text in ("你确定吗", "你刚才说错了", "重新查", "不是这个比赛"):
            with self.subTest(text=text):
                intents = decide_intents(
                    text=text, has_image=False, has_audio=False, face_ids=[]
                )
                search = [item for item in intents if item.name == "search.web"]
                self.assertEqual(len(search), 1)
                self.assertEqual(search[0].args["correction"], "true")

    def test_implicit_fresh_news_question_triggers_web_search(self) -> None:
        intents = decide_intents(
            text="昨天上海发生了哪些重要新闻？",
            has_image=False,
            has_audio=False,
            face_ids=[],
        )
        self.assertIn("search.web", [item.name for item in intents])


if __name__ == "__main__":
    unittest.main()
