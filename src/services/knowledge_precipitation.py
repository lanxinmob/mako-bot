"""Daily long-term-memory and user-profile consolidation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Iterable

from nonebot.log import logger

from src.models.schemas import ChatRecord
from src.services.llm import get_deepseek_client, has_deepseek
from src.services.storage import StorageService
from src.services.vector_store import VectorStore


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


class KnowledgePrecipitationService:
    def __init__(
        self,
        storage: StorageService | None = None,
        vector_store: VectorStore | None = None,
    ) -> None:
        self.storage = storage or StorageService()
        self.vector_store = vector_store or VectorStore()

    async def run(self, *, hours: int = 24) -> PrecipitationResult:
        if not has_deepseek():
            return PrecipitationResult(skipped_reason="DEEPSEEK_API_KEY is not configured")

        records = await asyncio.to_thread(self.storage.get_recent_global_records, hours)
        records = sorted(records, key=lambda item: item.time)[-500:]
        if not records:
            return PrecipitationResult(skipped_reason="no recent chat records")

        points = await self._extract_knowledge(records)
        stored = 0
        for point in points:
            try:
                await asyncio.to_thread(self.vector_store.add, point)
                stored += 1
            except Exception as exc:
                logger.warning("长期记忆写入失败 point={} error={}", point[:80], exc)

        profiles = 0
        user_ids = sorted({item.user_id for item in records if item.role == "user" and item.user_id})
        for user_id in user_ids:
            user_records = [
                item for item in records if item.role == "user" and item.user_id == user_id
            ]
            try:
                await self._update_profile(user_id, user_records)
                profiles += 1
            except Exception as exc:
                logger.warning("用户画像更新失败 user_id={} error={}", user_id, exc)

        return PrecipitationResult(
            records=len(records),
            knowledge_points=stored,
            profiles_updated=profiles,
        )

    async def _extract_knowledge(self, records: list[ChatRecord]) -> list[str]:
        transcript = _bounded_text(self._format_record(item) for item in records)
        prompt = f"""
从最近聊天中提炼值得长期保留的共享事件或知识。忽略寒暄、临时指令、密码、令牌和私人敏感信息。
每条必须是独立完整的一句话；涉及具体用户时保留用户 ID；最多 20 条；只输出无序列表。

聊天记录：
{transcript}
""".strip()
        response = await asyncio.wait_for(
            get_deepseek_client().chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
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

    async def _update_profile(self, user_id: int, records: list[ChatRecord]) -> None:
        nickname = next((item.nickname for item in records if item.nickname), str(user_id))
        old_profile = await asyncio.to_thread(self.storage.get_profile, user_id)
        old_text = (old_profile or {}).get("profile_text") or "暂无历史画像。"
        transcript = _bounded_text((item.content for item in records), max_chars=8000)
        prompt = f"""
更新用户 {nickname}（{user_id}）的画像。只依据用户明确表达且相对稳定的信息；不要把玩笑、一次性请求或推测写成事实。
不要保存密码、令牌、精确住址等敏感信息。保持以下四段格式：
【核心特质】【行为模式】【关系定位】【茉子认知画像】

历史画像：
{old_text}

最近发言：
{transcript}
""".strip()
        response = await asyncio.wait_for(
            get_deepseek_client().chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=1400,
            ),
            timeout=40.0,
        )
        profile_text = (response.choices[0].message.content or "").strip()
        if profile_text:
            await asyncio.to_thread(
                self.storage.set_profile,
                user_id,
                nickname,
                profile_text,
            )

    @staticmethod
    def _format_record(record: ChatRecord) -> str:
        if record.role == "user":
            return f"user[{record.nickname or record.user_id}_{record.user_id}]: {record.content}"
        return f"assistant: {record.content}"
