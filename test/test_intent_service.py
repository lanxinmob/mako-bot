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


if __name__ == "__main__":
    unittest.main()
