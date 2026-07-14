"""Deterministic application plugin selection and loading."""

from __future__ import annotations

from collections.abc import Callable, Iterable

import nonebot

from src.core.config import get_settings


APPLICATION_PLUGINS = (
    "chat",
    "autonomy",
    "governance",
    "health",
    "dashboard",
    "scheduler",
    "weather",
    "what_to_eat",
    "precipitate_knowledge",
    "relationship_followups",
)
REQUIRED_PLUGINS = frozenset({"chat", "health"})


def select_application_plugins(configured: Iterable[str]) -> tuple[str, ...]:
    requested = {item.strip() for item in configured if item.strip()}
    unknown = requested.difference(APPLICATION_PLUGINS)
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ValueError(f"Unknown application plugins: {names}")
    selected = requested | REQUIRED_PLUGINS if requested else set(APPLICATION_PLUGINS)
    return tuple(name for name in APPLICATION_PLUGINS if name in selected)


def load_application_plugins(
    *,
    loader: Callable[[str], object | None] = nonebot.load_plugin,
) -> tuple[str, ...]:
    settings = get_settings()
    configured = settings.parse_name_list(settings.plugin_enable_list)
    selected = select_application_plugins(configured)
    for name in selected:
        module = f"src.plugins.{name}"
        if loader(module) is None:
            raise RuntimeError(f"Failed to load application plugin: {module}")
    return selected
