from __future__ import annotations

import pytest

from src.core.bootstrap import APPLICATION_PLUGINS, select_application_plugins


def test_default_bootstrap_loads_the_complete_application() -> None:
    assert select_application_plugins([]) == APPLICATION_PLUGINS


def test_configured_plugins_keep_required_runtime_boundaries() -> None:
    assert select_application_plugins(["weather"]) == ("chat", "health", "weather")


def test_unknown_plugin_name_fails_fast() -> None:
    with pytest.raises(ValueError, match="Unknown application plugins: typo"):
        select_application_plugins(["typo"])
