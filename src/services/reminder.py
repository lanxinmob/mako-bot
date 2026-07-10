"""Reminder parsing and in-process reminder state.

Scheduling and message delivery remain in the NoneBot adapter.  This module
owns the domain rules so the adapter only translates events into operations.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

from nonebot.log import logger

from src.services.llm import get_deepseek_client, has_deepseek


@dataclass(frozen=True)
class Reminder:
    job_id: str
    content: str
    remind_time: datetime


def generate_job_id(group_id: int, user_id: int, remind_time: datetime) -> str:
    raw = f"{group_id}_{user_id}_{remind_time.isoformat()}"
    return f"reminder_{hashlib.md5(raw.encode()).hexdigest()}"


def extract_json_object(text: str) -> Optional[dict]:
    content = (text or "").strip()
    if "```json" in content:
        content = content.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in content:
        content = content.split("```", 1)[1].split("```", 1)[0].strip()
    if not content.startswith("{"):
        start, end = content.find("{"), content.rfind("}")
        if start < 0 or end <= start:
            return None
        content = content[start : end + 1]
    try:
        value = json.loads(content)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


class ReminderIntentParser:
    async def parse(self, user_text: str, now: datetime) -> dict:
        if not has_deepseek():
            return {"intent": "NONE"}
        prompt = f"""
请分析用户的意图，判断是创建、修改、删除提醒，还是普通聊天。
当前时间是：{now.strftime('%Y-%m-%d %H:%M:%S')}
用户说：{user_text!r}

只返回 JSON：
- 创建：{{"intent":"CREATE","remind_time":"YYYY-MM-DDTHH:MM:SS","content":"提醒内容"}}
- 修改：{{"intent":"MODIFY","target_content":"关键词","new_remind_time":"YYYY-MM-DDTHH:MM:SS","new_content":"新内容"}}
- 删除：{{"intent":"DELETE","target_content":"关键词"}}
- 普通聊天：{{"intent":"NONE"}}
"""
        try:
            response = await asyncio.wait_for(
                get_deepseek_client().chat.completions.create(
                    model="deepseek-chat",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    max_tokens=500,
                ),
                timeout=10.0,
            )
            data = extract_json_object(response.choices[0].message.content or "")
            return data or {"intent": "NONE"}
        except Exception as exc:
            logger.warning(f"提醒意图解析失败: {exc}")
            return {"intent": "NONE"}


class ReminderBook:
    """Small state owner for reminders scheduled by the current process."""

    def __init__(self) -> None:
        self._items: Dict[str, List[Reminder]] = {}

    def list(self, session_id: str) -> List[Reminder]:
        return list(self._items.get(session_id, ()))

    def add(self, session_id: str, reminder: Reminder) -> None:
        self._items.setdefault(session_id, []).append(reminder)

    def find(self, session_id: str, keyword: str) -> Optional[Reminder]:
        return next(
            (item for item in self._items.get(session_id, ()) if keyword in item.content),
            None,
        )

    def remove(self, session_id: str, job_id: str) -> Optional[Reminder]:
        items = self._items.get(session_id, [])
        for index, item in enumerate(items):
            if item.job_id == job_id:
                removed = items.pop(index)
                if not items:
                    self._items.pop(session_id, None)
                return removed
        return None

