from __future__ import annotations

import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter


def test_autonomy_plugin_loads_and_parses_intent() -> None:
    nonebot.init()
    nonebot.get_driver().register_adapter(OneBotV11Adapter)
    plugin = nonebot.load_plugin("src.plugins.autonomy")
    assert plugin is not None

    from src.plugins.autonomy import parse_decision

    decision = parse_decision(
        {
            "action": "speak",
            "target_type": "group",
            "target_id": 12345,
            "confidence": 0.9,
            "risk": "low",
            "intent": "daily_greeting",
            "message": "大家早上好",
            "reason": "自然问候",
        }
    )
    assert decision.intent == "greeting"
