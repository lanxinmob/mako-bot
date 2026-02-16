from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import List, Optional

from src.core.config import get_settings
from src.models.schemas import RelationshipMemory
from src.services.notes import NoteService
from src.services.storage import StorageService
from src.services.vector_store import VectorStore


class RelationshipService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.storage = StorageService()
        self.note_service = NoteService()
        self.vector_store = VectorStore()

    def absorb_user_message(self, user_id: int, nickname: str, text: str) -> List[RelationshipMemory]:
        text = text.strip()
        if not text:
            return []
        created: List[RelationshipMemory] = []
        for memory in self._extract_preferences(user_id, text):
            created.append(memory)
        for memory in self._extract_taboos(user_id, text):
            created.append(memory)
        for memory in self._extract_promises(user_id, text):
            created.append(memory)
        event = self._extract_event(user_id, nickname, text)
        if event:
            created.append(event)

        if created:
            self._sync_profile(user_id=user_id, nickname=nickname)
            for memory in created:
                self._sync_note(memory)
        return created

    def build_memory_brief(self, user_id: int, limit_each: int = 3) -> str:
        preferences = self.storage.list_relationship_memories(
            user_id, memory_type="preference", status="active", limit=limit_each
        )
        taboos = self.storage.list_relationship_memories(
            user_id, memory_type="taboo", status="active", limit=limit_each
        )
        events = self.storage.list_relationship_memories(
            user_id, memory_type="event", status="active", limit=limit_each
        )
        promises = self.storage.list_relationship_memories(
            user_id, memory_type="promise", status="active", limit=limit_each
        )
        chunks: List[str] = []
        if preferences:
            chunks.append("偏好:\n" + "\n".join([f"- {m.content}" for m in preferences]))
        if taboos:
            chunks.append("禁忌:\n" + "\n".join([f"- {m.content}" for m in taboos]))
        if events:
            chunks.append("近期事件:\n" + "\n".join([f"- {m.content}" for m in events]))
        if promises:
            chunks.append("待跟进承诺:\n" + "\n".join([f"- {m.content}" for m in promises]))
        return "\n\n".join(chunks).strip()

    def get_due_followups(self, limit: int = 20) -> List[RelationshipMemory]:
        return self.storage.list_due_followups(limit=limit)

    def mark_done(self, user_id: int, memory_id: str) -> bool:
        return self.storage.mark_relationship_done(user_id, memory_id)

    def _create(
        self,
        user_id: int,
        memory_type: str,
        content: str,
        *,
        source: str = "chat",
        confidence: float = 0.8,
        due_at: Optional[datetime] = None,
    ) -> RelationshipMemory:
        memory = self.storage.add_relationship_memory(
            user_id,
            memory_type,
            content,
            source=source,
            confidence=confidence,
            due_at=due_at,
        )
        self.vector_store.add(f"[relation:{memory_type}:{user_id}] {content}")
        return memory

    def _sync_note(self, memory: RelationshipMemory) -> None:
        title_map = {
            "preference": "用户偏好",
            "taboo": "用户禁忌",
            "event": "关系事件",
            "promise": "跟进承诺",
        }
        title = title_map.get(memory.memory_type, "关系记忆")
        note_title = f"{title}:{memory.memory_id}"
        note_content = memory.content
        self.note_service.add_note(
            user_id=memory.user_id,
            title=note_title,
            content=note_content,
            category="relationship",
        )

    def _sync_profile(self, user_id: int, nickname: str) -> None:
        prefs = self.storage.list_relationship_memories(
            user_id, memory_type="preference", status="active", limit=3
        )
        taboos = self.storage.list_relationship_memories(
            user_id, memory_type="taboo", status="active", limit=3
        )
        events = self.storage.list_relationship_memories(
            user_id, memory_type="event", status="active", limit=2
        )
        profile_lines: List[str] = [f"称呼偏好: {nickname}"]
        if prefs:
            profile_lines.append("偏好: " + "；".join([m.content for m in prefs]))
        if taboos:
            profile_lines.append("禁忌: " + "；".join([m.content for m in taboos]))
        if events:
            profile_lines.append("近期事件: " + "；".join([m.content for m in events]))
        profile_lines.append(f"最后更新: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        self.storage.set_profile(user_id, nickname, "\n".join(profile_lines))

    def _extract_preferences(self, user_id: int, text: str) -> List[RelationshipMemory]:
        patterns = [
            r"我喜欢(.+)",
            r"我爱(.+)",
            r"我不喜欢(.+)",
            r"我讨厌(.+)",
        ]
        created: List[RelationshipMemory] = []
        for pattern in patterns:
            match = re.search(pattern, text)
            if not match:
                continue
            detail = match.group(1).strip("。!！?？ ")
            if not detail:
                continue
            created.append(self._create(user_id, "preference", detail, confidence=0.85))
            break
        return created

    def _extract_taboos(self, user_id: int, text: str) -> List[RelationshipMemory]:
        patterns = [
            r"别(再)?(.+)",
            r"不要(.+)",
            r"不许(.+)",
        ]
        created: List[RelationshipMemory] = []
        for pattern in patterns:
            match = re.search(pattern, text)
            if not match:
                continue
            detail = match.group(match.lastindex or 1).strip("。!！?？ ")
            if not detail:
                continue
            created.append(self._create(user_id, "taboo", detail, confidence=0.9))
            break
        return created

    def _extract_promises(self, user_id: int, text: str) -> List[RelationshipMemory]:
        if not any(token in text for token in ["提醒我", "记得", "到时候", "跟进", "回头"]):
            return []
        due_at = self._parse_due_time(text)
        content = text.strip("。!！?？ ")
        return [self._create(user_id, "promise", content, confidence=0.95, due_at=due_at)]

    def _extract_event(self, user_id: int, nickname: str, text: str) -> Optional[RelationshipMemory]:
        if len(text) > 180:
            return None
        if not any(token in text for token in ["今天", "刚刚", "最近", "我在", "我准备", "我打算"]):
            return None
        content = f"{nickname}: {text.strip()}"
        return self._create(user_id, "event", content, confidence=0.7)

    def _parse_due_time(self, text: str) -> datetime:
        now = datetime.now()
        due = now + timedelta(hours=self.settings.proactive_default_hours)
        if "明天" in text:
            due = now + timedelta(days=1)
        elif "后天" in text:
            due = now + timedelta(days=2)
        elif "今晚" in text:
            due = now.replace(hour=20, minute=0, second=0, microsecond=0)
            if due <= now:
                due = due + timedelta(days=1)

        hour_match = re.search(r"(\d{1,2})\s*点", text)
        if hour_match:
            hour = max(0, min(23, int(hour_match.group(1))))
            due = due.replace(hour=hour, minute=0, second=0, microsecond=0)
            if due <= now:
                due = due + timedelta(days=1)
        return due
