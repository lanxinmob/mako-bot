from __future__ import annotations

import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter
from nonebot.log import logger

from src.core.config import get_settings
from src.core.logging import setup_logging

settings = get_settings()
setup_logging()

nonebot.init(_env_file=".env", host=settings.host, port=settings.port)
driver = nonebot.get_driver()
driver.register_adapter(OneBotV11Adapter)

default_plugins = [
    "src.plugins.chat",
    "src.plugins.governance",
    "src.plugins.scheduler",
    "src.plugins.weather",
    "src.plugins.what_to_eat",
    "src.plugins.precipitate_knowledge",
]
enabled_plugins = settings.parse_name_list(settings.plugin_enable_list)
plugins_to_load = [p for p in default_plugins if not enabled_plugins or p in enabled_plugins]
for plugin in plugins_to_load:
    nonebot.load_plugin(plugin)
    logger.info(f"plugin loaded: {plugin}")

if __name__ == "__main__":
    nonebot.run()
