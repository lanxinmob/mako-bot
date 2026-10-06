from __future__ import annotations

import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter


def test_chat_plugin_loads_through_nonebot() -> None:
    """Exercise the real plugin boundary instead of importing helpers only."""

    nonebot.init()
    nonebot.get_driver().register_adapter(OneBotV11Adapter)
    plugin = nonebot.load_plugin("src.plugins.chat")
    assert plugin is not None

