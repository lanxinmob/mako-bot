from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from nonebot.adapters.onebot.v11 import MessageSegment
from nonebot.log import logger

from src.core.errors import NotConfiguredError
from src.services.affinity import AffinityService
from src.services.amap import geocode, plan_route, search_poi
from src.services.emoji import analyze_emoji
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
    context_lines: List[str] = field(default_factory=list)
    extra_messages: List[MessageSegment] = field(default_factory=list)
    handled: bool = False

    def context_text(self) -> str:
        return "\n".join(self.context_lines).strip()


class ToolExecutor:
    def __init__(self) -> None:
        self.note_service = NoteService()
        self.affinity_service = AffinityService()

    async def run(
        self,
        decisions: List[IntentDecision],
        user_id: int,
        text: str,
        image_urls: List[str],
        audio_urls: List[str],
        face_ids: List[int],
    ) -> ToolExecutionResult:
        result = ToolExecutionResult()
        for decision in decisions:
            try:
                await self._run_one(decision, result, user_id, text, image_urls, audio_urls, face_ids)
                result.handled = True
            except NotConfiguredError as exc:
                result.context_lines.append(f"[{decision.name}] 未配置: {exc}")
            except Exception as exc:
                logger.exception(f"Tool execution failed: {decision.name}, {exc}")
                result.context_lines.append(f"[{decision.name}] 调用失败: {exc}")
        return result

    async def _run_one(
        self,
        decision: IntentDecision,
        result: ToolExecutionResult,
        user_id: int,
        text: str,
        image_urls: List[str],
        audio_urls: List[str],
        face_ids: List[int],
    ) -> None:
        name = decision.name
        args = decision.args

        if name == "image.describe":
            if not image_urls:
                result.context_lines.append("图片理解：未检测到可访问图片。")
                return
            desc = await describe_image_url(image_urls[0])
            result.context_lines.append(f"图片理解结果：{desc}")
            return

        if name == "image.generate":
            prompt = args.get("prompt") or text
            url = await generate_image(prompt)
            result.context_lines.append(f"图片生成成功，提示词：{prompt}")
            result.extra_messages.append(MessageSegment.image(file=url))
            return

        if name == "image.process":
            if not image_urls:
                result.context_lines.append("图片处理：未检测到可访问图片。")
                return
            raw = await download_image_bytes(image_urls[0])
            out = await process_image(raw, args.get("operation", "grayscale"), args.get("value") or None)
            if not out:
                result.context_lines.append("图片处理失败：输入图片无效。")
                return
            suffix = ".png" if out.startswith(b"\x89PNG") else ".jpg"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
                f.write(out)
                path = Path(f.name)
            result.context_lines.append(
                f"图片处理完成，操作={args.get('operation')} 参数={args.get('value', '')}".strip()
            )
            result.extra_messages.append(MessageSegment.image(file=str(path)))
            return

        if name == "language.translate":
            translated = await translate_text(args.get("text", text), args.get("target_lang", "ZH"))
            result.context_lines.append(f"翻译结果：{translated}")
            return

        if name == "language.detect":
            lang = detect_language(args.get("text", text))
            result.context_lines.append(f"语言识别结果：{lang}")
            return

        if name == "language.tts":
            audio = await text_to_speech(args.get("text", text))
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
                f.write(audio)
                path = Path(f.name)
            result.context_lines.append("已将文本转换为语音。")
            result.extra_messages.append(MessageSegment.record(file=str(path)))
            return

        if name == "language.stt":
            if not audio_urls:
                result.context_lines.append("语音转文字：未检测到语音消息。")
                return
            audio = await download_image_bytes(audio_urls[0])
            transcript = await speech_to_text(audio, filename="audio.mp3")
            result.context_lines.append(f"语音识别结果：{transcript}")
            return

        if name == "affinity.query":
            score = self.affinity_service.get_score(user_id)
            level = self.affinity_service.level(score)
            result.context_lines.append(f"当前好感度：{score}（{level}）")
            return

        if name == "emoji.analyze":
            analysis = analyze_emoji(face_ids, text)
            score = self.affinity_service.adjust(user_id, analysis.affinity_delta)
            labels = "、".join(analysis.labels) if analysis.labels else "无明显特征"
            result.context_lines.append(
                f"表情识别：{labels}，情绪={analysis.sentiment}，好感度已调整为 {score}"
            )
            return

        if name == "note.add":
            note = self.note_service.add_note(
                user_id=user_id,
                title=args.get("title", "未命名笔记"),
                content=args.get("content", text),
            )
            result.context_lines.append(f"笔记已记录：{note.note_id}《{note.title}》")
            return

        if name == "note.query":
            keyword = args.get("keyword", "")
            notes = (
                self.note_service.search_notes(user_id, keyword) if keyword else self.note_service.list_notes(user_id)
            )
            if not notes:
                result.context_lines.append("笔记查询：没有匹配内容。")
                return
            top = notes[:5]
            formatted = "\n".join([f"- {n.note_id} | {n.title} | {n.content[:50]}" for n in top])
            result.context_lines.append(f"笔记查询结果：\n{formatted}")
            return

        if name == "note.delete":
            ok = self.note_service.delete_note(user_id, args.get("keyword", ""))
            result.context_lines.append("笔记删除成功。" if ok else "笔记删除失败：未找到目标。")
            return

        if name == "note.update":
            updated = self.note_service.update_note(
                user_id, args.get("keyword", ""), args.get("content", "")
            )
            if updated:
                result.context_lines.append(f"笔记更新成功：{updated.note_id}《{updated.title}》")
            else:
                result.context_lines.append("笔记更新失败：未找到目标。")
            return

        if name == "map.query":
            await self._handle_map_query(result, args.get("text", text))
            return

        if name == "weather.query":
            await self._handle_weather_query(result, args.get("text", text))
            return

        if name == "search.web":
            query = args.get("query", text)
            items = await google_search(query, num=5)
            if not items:
                result.context_lines.append("搜索结果为空。")
                return
            lines = [f"- {item.title}\n  {item.link}\n  {item.snippet}" for item in items[:5]]
            result.context_lines.append(f"Google 搜索结果：\n" + "\n".join(lines))
            return

        if name == "search.summarize_url":
            url = args.get("url", "")
            page_text = await fetch_page_text(url)
            if not page_text:
                result.context_lines.append("链接总结失败：网页内容为空。")
                return
            summary = await self._summarize_text(page_text[:3500])
            result.context_lines.append(f"链接总结（{url}）：{summary}")
            return

    async def _summarize_text(self, text: str) -> str:
        prompt = "请用中文在120字内总结以下网页内容并保留关键事实：\n" + text
        if has_deepseek():
            client = get_deepseek_client()
            response = await client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=300,
            )
            return response.choices[0].message.content.strip()
        if has_openai():
            client = get_openai_client()
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=300,
            )
            return response.choices[0].message.content.strip()
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
                result.context_lines.append("地图查询：起点或终点解析失败。")
                return
            route = await plan_route(origin["location"], destination["location"], mode="walking")
            if not route:
                result.context_lines.append("地图查询：未获取到路线。")
                return
            result.context_lines.append(
                f"路线规划：{start} -> {end}，距离 {route.get('distance')} 米，"
                f"耗时 {route.get('duration')} 秒。"
            )
            return

        nearby_match = re.search(r"(.+?)附近(有什么|哪里有|有啥|)$", text)
        if nearby_match:
            keyword = nearby_match.group(1).strip() or "餐厅"
            pois = await search_poi(keyword=keyword, limit=5)
            if not pois:
                result.context_lines.append("地图查询：未找到周边结果。")
                return
            lines = [f"- {p['name']} | {p['address']}" for p in pois]
            result.context_lines.append("周边查询：\n" + "\n".join(lines))
            return

        target = text.replace("地图", "").replace("高德", "").replace("在哪", "").strip()
        if not target:
            return
        place = await geocode(target)
        if not place:
            result.context_lines.append("地图查询：地址解析失败。")
            return
        result.context_lines.append(
            f"地点信息：{place.get('formatted_address')}，坐标 {place.get('location')}。"
        )

    async def _handle_weather_query(self, result: ToolExecutionResult, text: str) -> None:
        import re

        city_match = re.search(r"([^\s，。！？,.!?]{2,10})(?:天气|气温)", text)
        city = city_match.group(1) if city_match else "北京"
        weather = await get_weather(city)
        if not weather:
            result.context_lines.append(f"天气查询：未找到 {city} 天气。")
            return
        result.context_lines.append(
            f"天气：{weather['country']}{weather['city']} {weather['text']}，"
            f"{weather['temp']}C，体感 {weather['feels_like']}C，湿度 {weather['humidity']}%。"
        )
