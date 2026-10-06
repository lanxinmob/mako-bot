"""Run scoped checks without dotenv, live Redis or external HTTP transports.

Run from the new project with ../mako-bot/.venv/Scripts/python.exe.
The app boot subprocess also uses this guard, so it cannot bypass isolation.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys


def guard() -> None:
    import socket
    import dotenv
    import httpx
    import pydantic_settings.sources.providers.dotenv as settings_dotenv
    import redis

    def blocked(*args, **kwargs):
        raise AssertionError("Live external call disabled for autonomy verification")

    async def blocked_async(*args, **kwargs):
        blocked()

    # Block the readers themselves, before NoneBot or application initialization.
    dotenv.dotenv_values = lambda *args, **kwargs: {}
    dotenv.load_dotenv = lambda *args, **kwargs: False
    settings_dotenv.dotenv_values = dotenv.dotenv_values
    httpx.HTTPTransport.handle_request = blocked
    httpx.AsyncHTTPTransport.handle_async_request = blocked_async
    redis.Redis.execute_command = blocked
    socket.create_connection = blocked
    socket.getaddrinfo = blocked

    from src.core.config import Settings, get_settings
    Settings.model_config["env_file"] = None
    get_settings.cache_clear()
    os.environ.update(
        AUTONOMY_ENABLED="false", PROACTIVE_ENABLED="false",
        REDIS_REQUIRED="false", LLM_REQUIRED="false", LOG_FILE="",
        DEEPSEEK_API_KEY="", OPENAI_API_KEY="", GEMINI_API_KEY="",
    )


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[4]
    assert Path.cwd().resolve() == root, "Run with cwd=mako-bot-refactor"
    sys.path.insert(0, str(root))
    guard()
    if sys.argv[1:] == ["--boot"]:
        import bot
        print("BOOT_OK")
    else:
        import subprocess
        import pytest

        original_run = subprocess.run

        def guarded_run(args, *positional, **kwargs):
            if args == [sys.executable, "-c", "import bot; print('BOOT_OK')"]:
                args = [sys.executable, str(Path(__file__).resolve()), "--boot"]
            return original_run(args, *positional, **kwargs)

        subprocess.run = guarded_run
        raise SystemExit(pytest.main(["-q", "-p", "no:cacheprovider", *sys.argv[1:]]))
