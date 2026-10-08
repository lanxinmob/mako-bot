"""Daily long-term-memory and user-profile consolidation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Iterable

from nonebot.log import logger

from src.core.config import get_settings
from src.models.schemas import ChatRecord
from src.services.integrations.llm import get_deepseek_client
from src.services.integrations.llm import get_deepseek_model
from src.services.integrations.llm import has_deepseek
from src.services.persistence import StorageService
from src.services.memory.vector_store import VectorStore
from src.services.memory.image_archive import get_image_archive, memory_model_content, MAX_MEMORY_IMAGES
from src.services.integrations.vision_input import native_vision_enabled


@dataclass(frozen=True)
class PrecipitationResult:
    records: int = 0
    knowledge_points: int = 0
    profiles_updated: int = 0
    skipped_reason: str = ""


def _bounded_text(values: Iterable[str], max_chars: int = 12_000) -> str:
    lines: list[str] = []
    total = 0
    for value in values:
        compact = " ".join((value or "").split())
        if not compact:
            continue
        remaining = max_chars - total
        if remaining <= 0:
            break
        lines.append(compact[:remaining])
        total += len(lines[-1])
    return "\n".join(lines)


def _record_batches(records: list[ChatRecord], *, max_chars: int = 12_000):
    """Cover every record, splitting long messages rather than clipping a day."""
    batch: list[ChatRecord] = []
    size = 0
    image_count = 0
    for record in records:
        # Reserve enough space for identity and scene labels on each fragment.
        content_limit = max(1, max_chars - 256)
        content = record.content or "[空消息]"
        for offset in range(0, len(content), content_limit):
            images = record.image_urls[:MAX_MEMORY_IMAGES] if offset == 0 else []
            fragment = record.model_copy(update={"content": content[offset:offset + content_limit],
                                                  "image_urls": images})
            length = len(KnowledgePrecipitationService._format_record(fragment)) + 1
            if batch and (len(batch) >= 500 or size + length > max_chars
                          or image_count + len(images) > MAX_MEMORY_IMAGES):
                yield batch
                batch, size = [], 0
                image_count = 0
            batch.append(fragment)
            size += length
            image_count += len(images)
    if batch:
        yield batch


class KnowledgePrecipitationService:
    def __init__(
        self,
        storage: StorageService | None = None,
        vector_store: VectorStore | None = None,
        image_archive=None,
    ) -> None:
        self.storage = storage or StorageService()
        self.vector_store = vector_store or VectorStore()
        self.image_archive = image_archive or get_image_archive()

    async def run(self, *, hours: int = 24) -> PrecipitationResult:
        if not has_deepseek():
            return PrecipitationResult(skipped_reason="DEEPSEEK_API_KEY is not configured")

        records = await asyncio.to_thread(self.storage.get_recent_global_records, hours)
        records = sorted(records, key=lambda item: item.time)
        if self.image_archive.root.is_dir():
            try:
                await asyncio.to_thread(self.image_archive.prune,
                                        self.storage.iter_global_image_urls())
            except Exception:
                logger.warning("记忆图片清理跳过：保留范围未确认")
        if not records:
            return PrecipitationResult(skipped_reason="no recent chat records")

        stored = 0
        seen: set[str] = set()
        for batch in _record_batches(records):
            try:
                points = await self._extract_knowledge(batch)
            except Exception as exc:
                logger.warning("长期记忆提取失败 records={} error_type={}",
                               len(batch), type(exc).__name__)
                continue
            for point in points:
                key = point.casefold()
                if key in seen:
                    continue
                try:
                    await asyncio.to_thread(self.vector_store.add, point)
                    seen.add(key)
                    stored += 1
                except Exception as exc:
                    logger.warning("长期记忆写入失败 error_type={}", type(exc).__name__)

        profiles = 0
        by_user: dict[int, list[ChatRecord]] = {}
        for item in records:
            if item.role == "user" and item.user_id:
                by_user.setdefault(item.user_id, []).append(item)
        for user_id, user_records in sorted(by_user.items()):
            try:
                if await self._update_profile(user_id, user_records):
                    profiles += 1
            except Exception as exc:
                logger.warning("用户画像更新失败 user_id={} error_type={}",
                               user_id, type(exc).__name__)

        return PrecipitationResult(
            records=len(records),
            knowledge_points=stored,
            profiles_updated=profiles,
        )

    async def _extract_knowledge(self, records: list[ChatRecord]) -> list[str]:
        transcript = _bounded_text(self._format_record(item) for item in records)
        prompt = f"""
从最近聊天中提炼值得长期保留的共享事件或知识。忽略寒暄、临时指令、密码、令牌和私人敏感信息。
每条必须是独立完整的一句话；涉及具体用户时保留用户 ID，涉及群事件时保留群 ID。
不同群的事件不要混为一谈；最多 20 条；没有值得保存的信息时输出空内容；只输出无序列表。
图片是用户分享的内容，不代表图中人物就是发送者，也不代表图中事件发生在发送者身上。
看不到的图片不得推测；只提炼有上下文依据的内容。

聊天记录：
{transcript}
""".strip()
        model_content = await memory_model_content(
            prompt, records, self.image_archive, vision_enabled=native_vision_enabled(get_settings()),
        )
        response = await asyncio.wait_for(
            get_deepseek_client().chat.completions.create(
                model=get_deepseek_model(),
                messages=[{"role": "user", "content": model_content}],
                temperature=0.2,
                max_tokens=1600,
            ),
            timeout=40.0,
        )
        raw = response.choices[0].message.content or ""
        points: list[str] = []
        seen: set[str] = set()
        for line in raw.splitlines():
            point = line.strip().lstrip("-*•0123456789. ").strip()
            key = point.casefold()
            if len(point) < 4 or key in seen:
                continue
            seen.add(key)
            points.append(point[:500])
            if len(points) >= 20:
                break
        return points

    async def _update_profile(self, user_id: int, records: list[ChatRecord]) -> bool:
        nickname = next((item.nickname for item in reversed(records) if item.nickname), str(user_id))
        old_profile = await asyncio.to_thread(self.storage.get_profile, user_id)
        old_text = (old_profile or {}).get("profile_text") or "暂无历史画像。"
        updated = False
        for batch in _record_batches(records, max_chars=8000):
            transcript = _bounded_text((self._format_record(item) for item in batch), max_chars=8000)
            prompt = f"""
更新用户 {nickname}（{user_id}）的画像。只依据用户明确表达且相对稳定的信息；不要把玩笑、一次性请求或推测写成事实。
不要保存密码、令牌、精确住址等敏感信息。保持以下四段格式：
分享图片不能单独证明用户的身份、外貌、经历或稳定偏好；看不到的图片不得推测。
【核心特质】【行为模式】【关系定位】【茉子认知画像】

历史画像：
{old_text}

最近发言：
{transcript}
""".strip()
            model_content = await memory_model_content(
                prompt, batch, self.image_archive, vision_enabled=native_vision_enabled(get_settings()),
            )
            response = await asyncio.wait_for(
                get_deepseek_client().chat.completions.create(
                    model=get_deepseek_model(),
                    messages=[{"role": "user", "content": model_content}],
                    temperature=0.2,
                    max_tokens=1400,
                ),
                timeout=40.0,
            )
            profile_text = (response.choices[0].message.content or "").strip()
            if profile_text:
                old_text = profile_text
                updated = True
        if updated:
            await asyncio.to_thread(
                self.storage.set_profile,
                user_id,
                nickname,
                old_text,
            )
        return updated

    @staticmethod
    def _format_record(record: ChatRecord) -> str:
        scene = f"group[{record.group_id}]" if record.group_id else "private"
        if record.role == "user":
            return f"{scene} user[{(record.nickname or str(record.user_id))[:100]}_{record.user_id}]: {record.content}"
        return f"{scene} assistant: {record.content}"
