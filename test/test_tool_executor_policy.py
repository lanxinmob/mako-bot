from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from src.core.config import get_settings
from src.services.intent import IntentDecision
from src.services.tool_executor import ToolExecutor


class ToolExecutorPolicyTest(unittest.TestCase):
    def tearDown(self) -> None:
        get_settings.cache_clear()

    def test_requirements_check(self) -> None:
        ok, reason = ToolExecutor._tool_requirements_ok(
            IntentDecision(name="image.describe", args={}),
            image_urls=[],
            audio_urls=[],
        )
        self.assertFalse(ok)
        self.assertIn("image", reason)

    def test_dedupe_decisions(self) -> None:
        decisions = [
            IntentDecision(name="note.query", args={"keyword": "todo"}),
            IntentDecision(name="note.query", args={"keyword": "todo"}),
            IntentDecision(name="weather.query", args={"text": "beijing"}),
        ]
        deduped = ToolExecutor._dedupe_decisions(decisions)
        self.assertEqual(len(deduped), 2)
        self.assertEqual(deduped[0].name, "note.query")
        self.assertEqual(deduped[1].name, "weather.query")

    def test_enable_list_controls_tool_visibility(self) -> None:
        with patch.dict(
            os.environ,
            {
                "TOOL_ENABLE_LIST": "weather.query,note.query",
                "TOOL_DISABLE_LIST": "",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            executor = ToolExecutor()
            self.assertTrue(executor._is_enabled("weather.query"))
            self.assertFalse(executor._is_enabled("search.web"))


if __name__ == "__main__":
    unittest.main()
