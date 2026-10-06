"""Explicit tool dispatch, scheduling, error aggregation and charging."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Callable, List, Optional

from nonebot.log import logger

from src.core.config import Settings, get_settings
from src.core.errors import NotConfiguredError
from src.services.memory.affinity import AffinityService
from src.services.governance.service import GovernanceService
from src.services.tools.intent import IntentDecision
from src.services.memory.notes import NoteService

from . import local as local_tools, media, policy, text as text_tools
from .dependencies import ToolDependencies
from .models import ToolExecutionResult
from .temporary_files import TemporaryFiles


class ToolExecutor:
    def __init__(
        self, *, dependencies: Optional[ToolDependencies] = None,
        settings_factory: Callable[[], Settings] = get_settings,
        note_factory: Callable[[], NoteService] = NoteService,
        affinity_factory: Callable[[], AffinityService] = AffinityService,
        governance_factory: Callable[[], GovernanceService] = GovernanceService,
    ) -> None:
        self.settings = settings_factory()
        self.note_service = note_factory()
        self.affinity_service = affinity_factory()
        self.governance = governance_factory()
        self.dependencies = dependencies if dependencies is not None else ToolDependencies()
        self._enabled_names = set(self.settings.parse_name_list(self.settings.tool_enable_list))
        self._disabled_names = set(self.settings.parse_name_list(self.settings.tool_disable_list))
        self._concurrent_safe_tools = set(policy.CONCURRENT_SAFE_TOOLS)
        self._temporary_files = TemporaryFiles()
        self._temp_files = self._temporary_files._temp_files

    def _track_temp_file(self, path: Path) -> None:
        self._temporary_files._track_temp_file(path)

    def cleanup_temp_files(self) -> None:
        """Remove tracked temporary files after messages are sent."""
        self._temporary_files.cleanup_temp_files()

    def _is_enabled(self, tool_name: str) -> bool:
        return policy.is_enabled(tool_name, self._enabled_names, self._disabled_names)

    _dedupe_decisions = staticmethod(policy.dedupe_decisions)
    _tool_requirements_ok = staticmethod(policy.tool_requirements_ok)

    async def run(
        self,
        decisions: List[IntentDecision],
        user_id: int,
        text: str,
        image_urls: List[str],
        audio_urls: List[str],
        face_ids: List[int],
        *,
        message_type: str,
        group_id: Optional[int] = None,
        is_group_admin: bool = False,
    ) -> ToolExecutionResult:
        result = ToolExecutionResult()
        unique_decisions = self._dedupe_decisions(decisions)
        if not unique_decisions:
            return result

        concurrent: List[IntentDecision] = []
        sequential: List[IntentDecision] = []
        for decision in unique_decisions:
            if decision.name in self._concurrent_safe_tools:
                concurrent.append(decision)
            else:
                sequential.append(decision)

        if concurrent:
            sem = asyncio.Semaphore(max(1, self.settings.tool_max_concurrency))

            async def _run_with_sem(decision: IntentDecision) -> ToolExecutionResult:
                async with sem:
                    return await self._execute_decision(
                        decision=decision,
                        user_id=user_id,
                        text=text,
                        image_urls=image_urls,
                        audio_urls=audio_urls,
                        face_ids=face_ids,
                        message_type=message_type,
                        group_id=group_id,
                        is_group_admin=is_group_admin,
                    )

            partial_results = await asyncio.gather(*[_run_with_sem(d) for d in concurrent], return_exceptions=True)
            for idx, part in enumerate(partial_results):
                if isinstance(part, Exception):
                    result.diagnostic_lines.append(f"[{concurrent[idx].name}] 调用失败: {part}")
                    continue
                result.merge(part)

        for decision in sequential:
            partial = await self._execute_decision(
                decision=decision,
                user_id=user_id,
                text=text,
                image_urls=image_urls,
                audio_urls=audio_urls,
                face_ids=face_ids,
                message_type=message_type,
                group_id=group_id,
                is_group_admin=is_group_admin,
            )
            result.merge(partial)
        return result

    async def _execute_decision(
        self,
        *,
        decision: IntentDecision,
        user_id: int,
        text: str,
        image_urls: List[str],
        audio_urls: List[str],
        face_ids: List[int],
        message_type: str,
        group_id: Optional[int],
        is_group_admin: bool,
    ) -> ToolExecutionResult:
        local = ToolExecutionResult()

        rejection, estimated_cost = policy.check_admission(
            decision, user_id, image_urls, audio_urls,
            message_type=message_type, group_id=group_id, is_group_admin=is_group_admin,
            governance=self.governance, is_enabled=self._is_enabled,
            requirements_ok=self._tool_requirements_ok,
        )
        if rejection:
            local.diagnostic_lines.append(rejection)
            return local

        started = time.perf_counter()
        try:
            handled = await asyncio.wait_for(
                self._run_one(decision, local, user_id, text, image_urls, audio_urls, face_ids),
                timeout=self.settings.tool_timeout_seconds,
            )
            local.handled = handled
            if handled:
                self.governance.consume_cost(user_id, estimated_cost)
        except NotConfiguredError as exc:
            local.diagnostic_lines.append(f"[{decision.name}] 未配置: {exc}")
        except asyncio.TimeoutError:
            local.diagnostic_lines.append(
                f"[{decision.name}] timeout after {self.settings.tool_timeout_seconds:.1f}s"
            )
        except Exception as exc:
            logger.exception(f"Tool execution failed: {decision.name}, {exc}")
            local.diagnostic_lines.append(f"[{decision.name}] 调用失败: {exc}")
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.info(f"tool={decision.name} elapsed_ms={elapsed_ms:.1f}")
        return local

    async def _run_one(
        self,
        decision: IntentDecision,
        result: ToolExecutionResult,
        user_id: int,
        text: str,
        image_urls: List[str],
        audio_urls: List[str],
        face_ids: List[int],
    ) -> bool:
        name = decision.name

        if name in {
            "image.describe",
            "image.generate",
            "image.process",
            "language.tts",
            "language.stt",
        }:
            return await media.handle(
                decision, result, text, image_urls, audio_urls,
                track_temp_file=self._track_temp_file, dependencies=self.dependencies,
                temporary_files=self._temporary_files,
            )

        if name in {
            "language.translate",
            "language.detect",
            "search.web",
            "search.summarize_url",
        }:
            return await text_tools.handle(
                decision, result, text, summarize_text=self._summarize_text,
                dependencies=self.dependencies,
            )

        if name in {
            "affinity.query",
            "emoji.analyze",
            "note.add",
            "note.query",
            "note.delete",
            "note.update",
            "map.query",
            "weather.query",
        }:
            return await local_tools.handle(
                decision, result, user_id, text, face_ids,
                note_service=self.note_service, affinity_service=self.affinity_service,
                handle_map_query=self._handle_map_query, handle_weather_query=self._handle_weather_query,
                dependencies=self.dependencies,
            )

        result.diagnostic_lines.append(f"[{name}] unsupported tool name.")
        return False

    async def _summarize_text(self, text: str) -> str:
        return await text_tools.summarize_text(text, dependencies=self.dependencies)

    async def _handle_map_query(self, result: ToolExecutionResult, text: str) -> None:
        await local_tools.handle_map_query(result, text, dependencies=self.dependencies)

    async def _handle_weather_query(self, result: ToolExecutionResult, text: str) -> None:
        await local_tools.handle_weather_query(result, text, dependencies=self.dependencies)
