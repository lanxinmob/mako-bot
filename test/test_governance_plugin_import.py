from __future__ import annotations

import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter


def test_governance_plugin_loads_through_nonebot() -> None:
    nonebot.init()
    nonebot.get_driver().register_adapter(OneBotV11Adapter)
    assert nonebot.load_plugin("src.plugins.governance") is not None
