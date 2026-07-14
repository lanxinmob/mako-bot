"""Installable Mako-Bot application entrypoint."""

from __future__ import annotations

import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter

from src.core.bootstrap import load_application_plugins
from src.core.logging import setup_logging


_bootstrapped = False


def bootstrap_application():
    """Initialize NoneBot and load the complete application exactly once."""

    global _bootstrapped
    if _bootstrapped:
        return nonebot.get_driver()
    setup_logging()
    nonebot.init()
    driver = nonebot.get_driver()
    driver.register_adapter(OneBotV11Adapter)
    load_application_plugins()
    _bootstrapped = True
    return driver


def main() -> None:
    bootstrap_application()
    nonebot.run()
