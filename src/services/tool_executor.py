from __future__ import annotations

import asyncio
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from nonebot.adapters.onebot.v11 import MessageSegment
from nonebot.log import logger

from src.core.config import get_settings
from src.core.errors import NotConfiguredError
from src.services.affinity import AffinityService
from src.services.amap import geocode, plan_route, search_poi
from src.services.emoji import analyze_emoji
from src.services.governance import GovernanceService
from src.services.image import (
    describe_image_url,
    download_image_bytes,
    generate_image,
    process_image,
)
from src.services.intent import IntentDecision
from src.services.language import detect_language, speech_to_text, text_to_speech, translate_text
from src.services.llm import get_deepseek_client, get_openai_client, has_deepseek, has_openai
from src.services.notes import NoteService
from src.services.search import fetch_page_text, google_search
from src.services.weather import get_weather


@dataclass
class ToolExecutionResult:
    fact_lines: List[str] = field(default_factory=list)
    diagnostic_lines: List[str] = field(default_factory=list)
    extra_messages: List[MessageSegment] = field(default_factory=list)
    handled: bool = False

    def merge(self, other: "ToolExecutionResult") -> None:
        self.fact_lines.extend(other.fact_lines)
        self.diagnostic_lines.extend(other.diagnostic_lines)
        self.extra_messages.extend(other.extra_messages)
        self.handled = self.handled or other.handled

    def context_text(self) -> str:
        if self.fact_lines:
            return "\n".join(self.fact_lines).strip()
        if self.diagnostic_lines:
            return "\n".join(self.diagnostic_lines[:2]).strip()
        return ""


class ToolExecutor:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.note_service = NoteService()
        self.affinity_service = AffinityService()
        self.governance = GovernanceService()
        self._enabled_names = set(self.settings.parse_name_list(self.settings.tool_enable_list))
        self._disabled_names = set(self.settings.parse_name_list(self.settings.tool_disable_list))
        self._concurrent_safe_tools = {
            "image.describe",
            "language.detect",
            "affinity.query",
            "emoji.analyze",
            "weather.query",
            "search.web",
            "search.summarize_url",
            "map.query",
        }

    def _is_enabled(self, tool_name: str) -> bool:
        if tool_name in self._disabled_names:
            return False
        if self._enabled_names:
            return tool_name in self._enabled_names
        return True

    @staticmethod
    def _dedupe_decisions(decisions: List[IntentDecision]) -> List[IntentDecision]:
        seen: set[tuple[str, tuple[tuple[str, str], ...]]] = set()
        result: List[IntentDecision] = []
        for decision in decisions:
            key = (decision.name, tuple(sorted((decision.args or {}).items())))
            if key in seen:
                continue
            seen.add(key)
            result.append(decision)
        return result

    @staticmethod
    def _tool_requirements_ok(
        decision: IntentDecision,
        image_urls: List[str],
        audio_urls: List[str],
    ) -> tuple[bool, str]:
        if decision.name in {"image.describe", "image.process"} and not image_urls:
            return False, "requires image input"
        if decision.name == "language.stt" and not audio_urls:
            return False, "requires audio input"
        if decision.name == "search.summarize_url" and not decision.args.get("url"):
            return False, "requires a valid url"
        return True, ""

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

        if not self._is_enabled(decision.name):
            local.diagnostic_lines.append(f"[{decision.name}] skipped: disabled by config.")
            return local

        access = self.governance.tool_allowed(
            decision.name,
            user_id=user_id,
            message_type=message_type,
            group_id=group_id,
            is_group_admin=is_group_admin,
        )
        if not access.allowed:
            local.diagnostic_lines.append(f"[{decision.name}] skipped: {access.reason}.")
            return local

        usable, reason = self._tool_requirements_ok(decision, image_urls, audio_urls)
        if not usable:
            local.diagnostic_lines.append(f"[{decision.name}] skipped: {reason}.")
            return local

        estimated_cost = self.governance.estimate_tool_cost(decision.name)
        budget = self.governance.can_consume_cost(user_id, estimated_cost)
        if not budget.allowed:
            local.diagnostic_lines.append(f"[{decision.name}] skipped: {budget.reason}.")
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
        args = decision.args

        if name == "image.describe":
            desc = await describe_image_url(image_urls[0])
            result.fact_lines.append(f"图片理解结果: {desc}")
            return True

        if name == "image.generate":
            prompt = args.get("prompt") or text
            url = await generate_image(prompt)
            result.fact_lines.append(f"图片生成完成，提示词: {prompt}")
            result.extra_messages.append(MessageSegment.image(file=url))
            return True

        if name == "image.process":
            raw = await download_image_bytes(image_urls[0])
            out = await process_image(raw, args.get("operation", "grayscale"), args.get("value") or None)
            if not out:
                result.diagnostic_lines.append("图片处理失败: 输入图片无效。")
                return False
            suffix = ".png" if out.startswith(b"\x89PNG") else ".jpg"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
                f.write(out)
                path = Path(f.name)
            result.fact_lines.append(
                f"图片处理完成，操作={args.get('operation')} 参数={args.get('value', '')}".strip()
            )
            result.extra_messages.append(MessageSegment.image(file=str(path)))
            return True

        if name == "language.translate":
            translated = await translate_text(args.get("text", text), args.get("target_lang", "ZH"))
            result.fact_lines.append(f"翻译结果: {translated}")
            return True

        if name == "language.detect":
            lang = detect_language(args.get("text", text))
            result.fact_lines.append(f"语种识别结果: {lang}")
            return True

        if name == "language.tts":
            audio = await text_to_speech(args.get("text", text))
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
                f.write(audio)
                path = Path(f.name)
            result.fact_lines.append("已将文本转换成语音。")
            result.extra_messages.append(MessageSegment.record(file=str(path)))
            return True

        if name == "language.stt":
            audio = await download_image_bytes(audio_urls[0])
            transcript = await speech_to_text(audio, filename="audio.mp3")
            result.fact_lines.append(f"语音识别结果: {transcript}")
            return True

        if name == "affinity.query":
            score = self.affinity_service.get_score(user_id)
            level = self.affinity_service.level(score)
            result.fact_lines.append(f"当前好感度: {score} ({level})")
            return True

        if name == "emoji.analyze":
            analysis = analyze_emoji(face_ids, text)
            score = self.affinity_service.adjust(user_id, analysis.affinity_delta)
            labels = "、".join(analysis.labels) if analysis.labels else "无明显特征"
            result.fact_lines.append(f"表情识别: {labels}，情绪={analysis.sentiment}，好感度={score}")
            return True

        if name == "note.add":
            note = self.note_service.add_note(
                user_id=user_id,
                title=args.get("title", "未命名笔记"),
                content=args.get("content", text),
            )
            result.fact_lines.append(f"笔记已记录: {note.note_id}《{note.title}》")
            return True

        if name == "note.query":
            keyword = args.get("keyword", "")
            notes = (
                self.note_service.search_notes(user_id, keyword) if keyword else self.note_service.list_notes(user_id)
            )
            if not notes:
                result.fact_lines.append("笔记查询: 没有匹配内容。")
                return True
            top = notes[:5]
            formatted = "\n".join([f"- {n.note_id} | {n.title} | {n.content[:50]}" for n in top])
            result.fact_lines.append(f"笔记查询结果:\n{formatted}")
            return True

        if name == "note.delete":
            ok = self.note_service.delete_note(user_id, args.get("keyword", ""))
            result.fact_lines.append("笔记删除成功。" if ok else "笔记删除失败: 未找到目标。")
            return True

        if name == "note.update":
            updated = self.note_service.update_note(user_id, args.get("keyword", ""), args.get("content", ""))
            if updated:
                result.fact_lines.append(f"笔记更新成功: {updated.note_id}《{updated.title}》")
            else:
                result.fact_lines.append("笔记更新失败: 未找到目标。")
            return True

        if name == "map.query":
            await self._handle_map_query(result, args.get("text", text))
            return True

        if name == "weather.query":
            await self._handle_weather_query(result, args.get("text", text))
            return True

        if name == "search.web":
            query = args.get("query", text)
            items = await google_search(query, num=5)
            if not items:
                result.fact_lines.append("搜索结果为空。")
                return True
            lines = [f"- {item.title}\n  {item.link}\n  {item.snippet}" for item in items[:5]]
            result.fact_lines.append("Google 搜索结果:\n" + "\n".join(lines))
            return True

        if name == "search.summarize_url":
            url = args.get("url", "")
            page_text = await fetch_page_text(url)
            if not page_text:
                result.fact_lines.append("链接总结失败: 网页内容为空。")
                return True
            summary = await self._summarize_text(page_text[:3500])
            result.fact_lines.append(f"链接总结（{url}）: {summary}")
            return True

        result.diagnostic_lines.append(f"[{name}] unsupported tool name.")
        return False

    async def _summarize_text(self, text: str) -> str:
        prompt = "请用中文在120字内总结以下网页内容并保留关键事实:\n" + text
        if has_deepseek():
            client = get_deepseek_client()
            response = await client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=300,
            )
            return (response.choices[0].message.content or "").strip()
        if has_openai():
            client = get_openai_client()
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=300,
            )
            return (response.choices[0].message.content or "").strip()
        return text[:120]

    async def _handle_map_query(self, result: ToolExecutionResult, text: str) -> None:
        import re

        route_match = re.search(r"从(.+?)到(.+?)(怎么去|路线|路程|$)", text)
        if route_match:
            start = route_match.group(1).strip()
            end = route_match.group(2).strip()
            origin = await geocode(start)
            destination = await geocode(end)
            if not origin or not destination:
                result.fact_lines.append("地图查询: 起点或终点解析失败。")
                return
            route = await plan_route(origin["location"], destination["location"], mode="walking")
            if not route:
                result.fact_lines.append("地图查询: 未获取到路线。")
                return
            result.fact_lines.append(
                f"路线规划: {start} -> {end}，距离 {route.get('distance')} 米，耗时 {route.get('duration')} 秒。"
            )
            return

        nearby_match = re.search(r"(.+?)附近(有什么|哪里有|有啥|)$", text)
        if nearby_match:
            keyword = nearby_match.group(1).strip() or "餐厅"
            pois = await search_poi(keyword=keyword, limit=5)
            if not pois:
                result.fact_lines.append("地图查询: 未找到周边结果。")
                return
            lines = [f"- {p['name']} | {p['address']}" for p in pois]
            result.fact_lines.append("周边查询:\n" + "\n".join(lines))
            return

        target = text.replace("地图", "").replace("高德", "").replace("在哪", "").strip()
        if not target:
            return
        place = await geocode(target)
        if not place:
            result.fact_lines.append("地图查询: 地址解析失败。")
            return
        result.fact_lines.append(
            f"地点信息: {place.get('formatted_address')}，坐标 {place.get('location')}。"
        )

    async def _handle_weather_query(self, result: ToolExecutionResult, text: str) -> None:
        import re

        city_match = re.search(r"([^\s，。！？,.!?]{2,10})(?:天气|气温)", text)
        city = city_match.group(1) if city_match else "北京"
        weather = await get_weather(city)
        if not weather:
            result.fact_lines.append(f"天气查询: 未找到 {city} 的天气。")
            return
        result.fact_lines.append(
            f"天气: {weather['country']}{weather['city']} {weather['text']}，"
            f"{weather['temp']}C，体感 {weather['feels_like']}C，湿度 {weather['humidity']}%。"
        )
