import ast
import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.core.bootstrap import select_application_plugins
from src.services.delivery.periodic import period_deadline
from src.services.delivery.state import DeliverySpec, DeliveryUnavailable
from src.services.delivery.state.recovery import DeliveryRecovery
from test.delivery.test_sender_acknowledgement import load_function


def load_runner():
    path = Path(__file__).resolve().parents[3] / "src/plugins/chat/recovery.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    node = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == "_runner")
    namespace = {"select_application_plugins": select_application_plugins,
        "OutboundDedupService": Mock(), "_storage": Mock(), "DeliveryRecovery": DeliveryRecovery,
        "scheduler": SimpleNamespace(timezone=timezone.utc), "datetime": datetime, "get_bots": lambda: {}}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
    return namespace["_runner"]


def test_actual_recovery_policy_preserves_plugin_switches_period_and_target():
    factory = load_runner()
    settings = SimpleNamespace(plugin_enable_list="chat", proactive_enabled=True, default_group_id=1,
                               parse_name_list=lambda value: value.split(",") if value else [])
    period = datetime.now(timezone.utc).date()
    periodic = DeliverySpec("periodic", "99", "group", "1", "scheduler.good_morning",
                            period.isoformat(), "{}", period_deadline(period, timezone.utc))
    followup = replace(periodic, kind="followup", target_type="private", business_id="memory")
    runner = factory(object(), settings)
    assert not runner.allowed(periodic) and not runner.allowed(followup)
    settings.plugin_enable_list = ""
    runner = factory(object(), settings)
    assert runner.allowed(periodic) and runner.allowed(followup)
    assert not runner.allowed(replace(periodic, target_id="2"))
    assert not runner.allowed(replace(periodic, revision="2000-01-01"))
    assert not runner.allowed(replace(periodic, business_id="unregistered_task"))
    settings.proactive_enabled = False
    assert not runner.allowed(followup)


@pytest.mark.asyncio
@pytest.mark.parametrize("due_fails", [False, True])
async def test_recovery_job_retains_failed_action_cursor_after_reminder_page(due_fails):
    runner = SimpleNamespace(run_page=AsyncMock(side_effect=DeliveryUnavailable))
    reminders = SimpleNamespace(restore_page=AsyncMock(return_value=("23:0", 1)))
    effects = SimpleNamespace(run_page=AsyncMock(return_value=SimpleNamespace(next_cursor="43:0")))
    namespace = {"asyncio": asyncio, "_cursor": "17:0", "_reminder_cursor": "0:0",
        "_reminder_intents": False, "reminder_runtime": AsyncMock(return_value=reminders),
        "_storage": SimpleNamespace(redis=object()), "get_settings": Mock(),
        "_runner": Mock(return_value=runner), "logger": Mock(), "_effects_cursor": "41:0",
        "EffectScanner": Mock(return_value=effects), "_generation_cursor": "51:0",
        "_history_cursor": "61:0", "HistoryScanner": Mock(return_value=SimpleNamespace(
            run_page=AsyncMock(return_value=SimpleNamespace(next_cursor="63:0")))),
        "GenerationCostScanner": Mock(return_value=SimpleNamespace(
            run_due=AsyncMock(side_effect=DeliveryUnavailable if due_fails else None),
            repair_page=AsyncMock(return_value=SimpleNamespace(next_cursor="53:0"))))}
    tick = load_function("src/plugins/chat/recovery.py", "recover_background_deliveries", namespace)
    await tick()
    assert namespace["_cursor"] == "17:0"
    assert namespace["_reminder_cursor"] == "23:0"
    runner.run_page.assert_awaited_once_with("17:0", limit=3)
    assert namespace["logger"].warning.call_count == 1 + int(due_fails)
    namespace["GenerationCostScanner"].return_value.run_due.assert_awaited_once()
    effects.run_page.assert_awaited_once_with("41:0")
    assert namespace["_effects_cursor"] == "43:0"
    assert namespace["_generation_cursor"] == "53:0"
    assert namespace["_history_cursor"] == "63:0"
    namespace["HistoryScanner"].return_value.run_page.assert_awaited_once_with("61:0")


@pytest.mark.asyncio
async def test_reminder_recovery_error_does_not_block_other_delivery_recovery():
    runner = SimpleNamespace(run_page=AsyncMock(return_value=("31:0", ())))
    namespace = {"asyncio": asyncio, "_cursor": "17:0", "_reminder_cursor": "23:0",
        "_reminder_intents": True, "reminder_runtime": AsyncMock(side_effect=DeliveryUnavailable),
        "_storage": SimpleNamespace(redis=object()), "get_settings": Mock(),
        "_runner": Mock(return_value=runner), "logger": Mock(), "_effects_cursor": "41:0",
        "EffectScanner": Mock(return_value=SimpleNamespace(run_page=AsyncMock(side_effect=DeliveryUnavailable))),
        "_generation_cursor": "51:0", "GenerationCostScanner": Mock(return_value=SimpleNamespace(
            run_due=AsyncMock(side_effect=DeliveryUnavailable),
            repair_page=AsyncMock(side_effect=DeliveryUnavailable))),
        "_history_cursor": "61:0", "HistoryScanner": Mock(return_value=SimpleNamespace(
            run_page=AsyncMock(side_effect=DeliveryUnavailable)))}
    tick = load_function("src/plugins/chat/recovery.py", "recover_background_deliveries", namespace)
    await tick()
    assert namespace["_reminder_cursor"] == "23:0" and namespace["_reminder_intents"] is True
    assert namespace["_cursor"] == "31:0"
    runner.run_page.assert_awaited_once_with("17:0", limit=3)
    assert namespace["_effects_cursor"] == "41:0"
    assert namespace["_generation_cursor"] == "51:0"
    assert namespace["_history_cursor"] == "61:0"
