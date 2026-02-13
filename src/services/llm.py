from __future__ import annotations

from functools import lru_cache
from typing import Optional

from openai import AsyncOpenAI

from src.core.config import get_settings
from src.core.errors import NotConfiguredError


@lru_cache
def get_openai_client() -> AsyncOpenAI:
    settings = get_settings()
    if not settings.openai_api_key:
        raise NotConfiguredError("OPENAI_API_KEY is not configured.")
    return AsyncOpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)


@lru_cache
def get_deepseek_client() -> AsyncOpenAI:
    settings = get_settings()
    if not settings.deepseek_api_key:
        raise NotConfiguredError("DEEPSEEK_API_KEY is not configured.")
    return AsyncOpenAI(api_key=settings.deepseek_api_key, base_url=settings.deepseek_base_url)


def has_openai() -> bool:
    settings = get_settings()
    return bool(settings.openai_api_key)


def has_deepseek() -> bool:
    settings = get_settings()
    return bool(settings.deepseek_api_key)
