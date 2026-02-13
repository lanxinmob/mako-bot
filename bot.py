from __future__ import annotations

import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter

from src.core.config import get_settings
from src.core.logging import setup_logging

settings = get_settings()
setup_logging()

nonebot.init(_env_file=".env", host=settings.host, port=settings.port)
driver = nonebot.get_driver()
driver.register_adapter(OneBotV11Adapter)

nonebot.load_plugin("src.plugins.chat")
nonebot.load_plugin("src.plugins.scheduler")
nonebot.load_plugin("src.plugins.weather")
nonebot.load_plugin("src.plugins.what_to_eat")
nonebot.load_plugin("src.plugins.precipitate_knowledge")

if __name__ == "__main__":
    nonebot.run()
