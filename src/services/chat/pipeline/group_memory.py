"""Persist group input before reply selection or command matchers consume it."""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from nonebot.log import logger

from src.models.schemas import ChatRecord


class GroupMemoryObserver:
    def __init__(self, services, *, capacity=10_000):
        self.services = services
        self.capacity = capacity
        self._seen: OrderedDict[tuple[str, int, str], None] = OrderedDict()
        self._lock: asyncio.Lock | None = None

    async def record(self, *, bot_id, message_id, user_id, group_id,
                     nickname, content, received_at):
        services = self.services
        if (not services.settings.record_undirected_group_messages
                or str(user_id) == str(bot_id)):
            return
        if self._lock is None:
            self._lock = asyncio.Lock()
        key = (str(bot_id), group_id, str(message_id))
        async with self._lock:
            if key in self._seen:
                return
            try:
                access = await asyncio.to_thread(services.governance.can_chat, user_id, group_id)
                if not access.allowed:
                    return
                await asyncio.to_thread(
                    services.storage.append_global_record,
                    ChatRecord(role="user", user_id=user_id, group_id=group_id,
                               nickname=nickname, content=content, time=received_at),
                )
            except Exception as exc:
                logger.warning("群消息记忆写入失败 error_type={}", type(exc).__name__)
                return
            self._seen[key] = None
            while len(self._seen) > self.capacity:
                self._seen.popitem(last=False)


def group_memory_text(normalized):
    """Retain text and media kinds, without downloading media or storing URLs."""
    labels = {"image": "图片", "record": "语音", "video": "视频",
              "face": "表情", "file": "文件", "forward": "合并转发"}
    parts = [normalized.plain_text] if normalized.plain_text else []
    for kind in normalized.segment_types:
        if kind in labels:
            parts.append(f"[{labels[kind]}]")
        elif kind != "text":
            parts.append(f"[{kind}]")
    return "\n".join(parts) or "[非文本消息]"
