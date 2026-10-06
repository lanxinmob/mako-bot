from __future__ import annotations

import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from src.core.config import Settings, get_settings
from src.core.errors import NotConfiguredError
from nonebot.adapters.onebot.v11 import MessageSegment
from src.services.governance.service import AccessDecision
from src.services.tools.intent import IntentDecision
from src.services.tools.executor import ToolExecutor


class ToolExecutorPolicyTest(unittest.TestCase):
    def tearDown(self) -> None:
        get_settings.cache_clear()

    def test_requirements_check(self) -> None:
        ok, reason = ToolExecutor._tool_requirements_ok(
            IntentDecision(name="image.describe", args={}),
            image_urls=[],
            audio_urls=[],
        )
        self.assertFalse(ok)
        self.assertIn("image", reason)

    def test_dedupe_decisions(self) -> None:
        decisions = [
            IntentDecision(name="note.query", args={"keyword": "todo"}),
            IntentDecision(name="note.query", args={"keyword": "todo"}),
            IntentDecision(name="weather.query", args={"text": "beijing"}),
        ]
        deduped = ToolExecutor._dedupe_decisions(decisions)
        self.assertEqual(len(deduped), 2)
        self.assertEqual(deduped[0].name, "note.query")
        self.assertEqual(deduped[1].name, "weather.query")

    def test_enable_list_controls_tool_visibility(self) -> None:
        with patch.dict(
            os.environ,
            {
                "TOOL_ENABLE_LIST": "weather.query,note.query",
                "TOOL_DISABLE_LIST": "",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            executor = ToolExecutor()
            self.assertTrue(executor._is_enabled("weather.query"))
            self.assertFalse(executor._is_enabled("search.web"))


@pytest.fixture
def executor():
    governance = MagicMock()
    governance.tool_allowed.return_value = AccessDecision(True)
    governance.can_consume_cost.return_value = AccessDecision(True)
    governance.estimate_tool_cost.return_value = 0.02
    settings = Settings(_env_file=None, tool_enable_list="", tool_disable_list="")
    service = ToolExecutor(
        settings_factory=lambda: settings,
        governance_factory=lambda: governance,
        note_factory=MagicMock, affinity_factory=MagicMock,
    )
    yield service
    service.cleanup_temp_files()


async def run_tools(executor, decisions, image_urls=None):
    return await executor.run(
        decisions, 42, "hello", image_urls or [], [], [],
        message_type="group", group_id=7, is_group_admin=True,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("denial", ["disabled", "governance", "input", "budget"])
async def test_rejection_stops_before_tool_side_effects(executor, denial):
    governance = executor.governance
    if denial == "disabled":
        executor._enabled_names.add("image.process")
        executor._disabled_names.add("image.process")
    elif denial == "governance":
        governance.tool_allowed.return_value = AccessDecision(False, "denied")
    elif denial == "budget":
        governance.can_consume_cost.return_value = AccessDecision(False, "budget exhausted")
    with patch.object(executor, "_run_one", new_callable=AsyncMock) as run_one:
        result = await run_tools(
            executor, [IntentDecision("image.process", {})],
            [] if denial == "input" else ["https://example.com/image.png"],
        )
    expected = {
        "disabled": "disabled by config", "governance": "denied",
        "input": "requires image input", "budget": "budget exhausted",
    }
    assert result.diagnostic_lines == [f"[image.process] skipped: {expected[denial]}."]
    assert not result.handled and not result.fact_lines and not result.extra_messages
    run_one.assert_not_awaited()
    executor.note_service.assert_not_called()
    assert executor.note_service.method_calls == []
    assert executor._temp_files == []
    governance.consume_cost.assert_not_called()
    if denial == "disabled":
        governance.tool_allowed.assert_not_called()
    else:
        governance.tool_allowed.assert_called_once_with(
            "image.process", user_id=42, message_type="group", group_id=7, is_group_admin=True,
        )
    if denial != "budget":
        governance.estimate_tool_cost.assert_not_called()
        governance.can_consume_cost.assert_not_called()
    else:
        assert governance.method_calls == [
            call.tool_allowed("image.process", user_id=42, message_type="group",
                              group_id=7, is_group_admin=True),
            call.estimate_tool_cost("image.process"), call.can_consume_cost(42, 0.02),
        ]


@pytest.mark.asyncio
async def test_concurrency_dedupe_and_merge_order(executor):
    executor.settings.tool_max_concurrency = 2
    released = asyncio.Event()
    active = peak = 0
    completed = []

    async def execute(decision, result, *_args):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        if decision.name == "image.describe":
            await released.wait()
        elif decision.name == "language.detect":
            released.set()
        else:
            assert completed == ["language.detect", "image.describe"]
        active -= 1
        completed.append(decision.name)
        result.fact_lines.append(decision.name)
        result.extra_messages.append(MessageSegment.text(decision.name))
        return True

    decisions = [IntentDecision(name, {}) for name in [
        "note.add", "image.describe", "language.detect", "image.describe",
    ]]
    with patch.object(executor, "_run_one", side_effect=execute):
        result = await run_tools(executor, decisions, ["test-image"])
    assert peak == 2
    assert completed == ["language.detect", "image.describe", "note.add"]
    assert result.fact_lines == ["image.describe", "language.detect", "note.add"]
    assert [m.data["text"] for m in result.extra_messages] == result.fact_lines
    assert result.handled and not result.diagnostic_lines
    assert executor.governance.consume_cost.call_args_list == [call(42, 0.02)] * 3


@pytest.mark.asyncio
@pytest.mark.parametrize("error, fragment", [
    (NotConfiguredError("missing"), "未配置: missing"),
    (RuntimeError("broken"), "调用失败: broken"),
    (asyncio.TimeoutError(), "timeout after"),
])
async def test_failed_adapter_does_not_charge(executor, error, fragment):
    with patch.object(executor.dependencies, "translate_text", AsyncMock(side_effect=error)) as translate:
        result = await run_tools(executor, [IntentDecision("language.translate", {})])
    translate.assert_awaited_once_with("hello", "ZH")
    assert fragment in result.diagnostic_lines[0]
    assert not result.handled
    executor.governance.consume_cost.assert_not_called()


@pytest.mark.asyncio
async def test_timeout_cancels_adapter_without_charge(executor):
    executor.settings.tool_timeout_seconds = 0.01
    cancelled = asyncio.Event()

    async def pending(*_args):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    with patch.object(executor.dependencies, "translate_text", side_effect=pending):
        result = await run_tools(executor, [IntentDecision("language.translate", {})])
    assert cancelled.is_set()
    assert "timeout after" in result.diagnostic_lines[0]
    executor.governance.consume_cost.assert_not_called()


@pytest.mark.asyncio
async def test_unsupported_tool_and_invalid_image_do_not_charge(executor):
    with (
        patch.object(executor.dependencies, "download_image_bytes", AsyncMock(return_value=b"bad")),
        patch.object(executor.dependencies, "process_image", AsyncMock(return_value=b"")),
    ):
        result = await run_tools(executor, [
            IntentDecision("image.process", {}), IntentDecision("unknown", {}),
        ], ["test-image"])
    assert result.diagnostic_lines == [
        "图片处理失败: 输入图片无效。", "[unknown] unsupported tool name.",
    ]
    assert not result.handled and not result.extra_messages
    assert executor._temp_files == []
    executor.governance.consume_cost.assert_not_called()


@pytest.mark.asyncio
async def test_text_local_dispatch_with_injected_adapters(executor):
    note = SimpleNamespace(note_id="n1", title="未命名笔记")
    executor.note_service.add_note.return_value = note
    with (
        patch.object(executor.dependencies, "translate_text", AsyncMock(return_value="译文")) as translate,
        patch.object(executor.dependencies, "get_weather", AsyncMock(return_value=None)) as weather,
        patch.object(executor.dependencies, "geocode", AsyncMock(side_effect=[
            {"location": "a"}, {"location": "b"},
        ])) as geocode,
        patch.object(executor.dependencies, "plan_route", AsyncMock(return_value={
            "distance": "10", "duration": "20",
        })) as route,
    ):
        result = await run_tools(executor, [
            IntentDecision("language.translate", {}), IntentDecision("note.add", {}),
            IntentDecision("weather.query", {"text": "北京天气"}),
            IntentDecision("map.query", {"text": "从甲到乙怎么去"}),
        ])
    assert result.fact_lines == [
        "天气查询: 未找到 北京 的天气。", "路线规划: 甲 -> 乙，距离 10 米，耗时 20 秒。",
        "翻译结果: 译文", "笔记已记录: n1《未命名笔记》",
    ]
    translate.assert_awaited_once_with("hello", "ZH")
    weather.assert_awaited_once_with("北京")
    assert geocode.await_args_list == [call("甲"), call("乙")]
    route.assert_awaited_once_with("a", "b", mode="walking")
    executor.note_service.add_note.assert_called_once_with(
        user_id=42, title="未命名笔记", content="hello",
    )


@pytest.mark.asyncio
async def test_url_summary_keeps_instance_override_and_input_limit(executor):
    with (
        patch.object(executor.dependencies, "fetch_page_text", AsyncMock(return_value="x" * 4000)) as fetch,
        patch.object(executor, "_summarize_text", AsyncMock(return_value="摘要")) as summarize,
    ):
        result = await run_tools(executor, [
            IntentDecision("search.summarize_url", {"url": "https://example.com/page"}),
        ])
    fetch.assert_awaited_once_with("https://example.com/page")
    summarize.assert_awaited_once_with("x" * 3500)
    assert result.fact_lines == ["链接总结（https://example.com/page）: 摘要"]


@pytest.mark.asyncio
async def test_concurrent_admission_error_is_aggregated_and_sequential_still_runs(executor):
    executor.governance.tool_allowed.side_effect = [RuntimeError("admission"), AccessDecision(True)]
    executor.note_service.delete_note.return_value = False
    result = await run_tools(executor, [
        IntentDecision("language.detect", {}), IntentDecision("note.delete", {}),
    ])
    assert result.diagnostic_lines == ["[language.detect] 调用失败: admission"]
    assert result.fact_lines == ["笔记删除失败: 未找到目标。"]
    assert result.handled
    assert result.context_text() == result.fact_lines[0]
    executor.governance.consume_cost.assert_called_once_with(42, 0.02)


if __name__ == "__main__":
    unittest.main()
