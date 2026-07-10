from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import List, Optional

from src.core.config import get_settings
from src.models.schemas import RelationshipMemory
from src.services.storage import StorageService


class RelationshipService:
    def __init__(
        self,
        *,
        storage: Optional[StorageService] = None,
    ) -> None:
        self.settings = get_settings()
        self.storage = storage or StorageService()

    def absorb_user_message(self, user_id: int, nickname: str, text: str) -> List[RelationshipMemory]:
        text = text.strip()
        if not text:
            return []
        existing_ids = {
            memory.memory_id
            for memory in self.storage.list_relationship_memories(user_id, status="", limit=100)
        }
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
        created = [memory for memory in created if memory.memory_id not in existing_ids]

        if created:
            self._sync_profile(user_id=user_id, nickname=nickname)
            for memory in created:
                self._sync_note(memory)
            self._append_progress_event(
                "relationship_memories_created",
                "从聊天中抽取并保存关系记忆。",
                {
                    "user_id": user_id,
                    "nickname": nickname,
                    "memory_count": len(created),
                    "memory_types": [memory.memory_type for memory in created],
                    "text_preview": text[:160],
                },
            )
            self._append_thought_trace(
                "relationship_extraction",
                "关系记忆抽取完成；仅保存命中的类型和摘要，不保存隐藏推理链。",
                {
                    "user_id": user_id,
                    "memory_count": len(created),
                    "memories": [
                        {
                            "memory_id": memory.memory_id,
                            "memory_type": memory.memory_type,
                            "content_preview": memory.content[:160],
                            "confidence": memory.confidence,
                        }
                        for memory in created
                    ],
                },
            )
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

    def list_memories(self, user_id: int, limit: int = 30) -> List[RelationshipMemory]:
        return self.storage.list_relationship_memories(user_id, status="", limit=limit)

    def format_memories(self, user_id: int, limit: int = 30) -> str:
        memories = self.list_memories(user_id, limit=limit)
        if not memories:
            return "茉子还没有保存你的关系记忆。"
        labels = {
            "preference": "偏好",
            "taboo": "边界",
            "event": "事件",
            "promise": "承诺",
        }
        lines = ["茉子当前只为你保存了这些关系记忆："]
        for memory in memories:
            status = "有效" if memory.status == "active" else "已完成"
            lines.append(
                f"- {memory.memory_id}｜{labels.get(memory.memory_type, memory.memory_type)}｜"
                f"{status}｜{memory.content}"
            )
        lines.append("可用“纠正记忆 ID 新内容”修改，或用“删除记忆 ID”删除。")
        return "\n".join(lines)

    def correct_memory(
        self,
        user_id: int,
        memory_id: str,
        content: str,
        *,
        nickname: str,
    ) -> Optional[RelationshipMemory]:
        content = content.strip()
        if not content:
            return None
        updated = self.storage.update_relationship_memory(user_id, memory_id, content)
        if not updated:
            return None
        self._update_mirror_note(updated)
        self._sync_profile(user_id, nickname)
        self._append_progress_event(
            "relationship_memory_corrected",
            "用户纠正了自己的关系记忆。",
            {"user_id": user_id, "memory_id": memory_id, "content_preview": content[:160]},
        )
        return updated

    def delete_memory(self, user_id: int, memory_id: str, *, nickname: str) -> bool:
        deleted = self.storage.delete_relationship_memory(user_id, memory_id)
        if not deleted:
            return False
        self.storage.delete_note(user_id, memory_id)
        self._sync_profile(user_id, nickname)
        self._append_progress_event(
            "relationship_memory_deleted",
            "用户删除了自己的关系记忆。",
            {"user_id": user_id, "memory_id": memory_id},
        )
        return True

    def relationship_stage(self, user_id: int) -> str:
        active_count = len(self.storage.list_relationship_memories(user_id, status="active", limit=100))
        score = self.storage.get_affinity(user_id)
        if active_count == 0:
            return "初识"
        if score >= 85 or active_count >= 8:
            return "亲近"
        if score >= 65 or active_count >= 4:
            return "信任建立"
        return "熟悉中"

    def get_due_followups(self, limit: int = 20) -> List[RelationshipMemory]:
        return self.storage.list_due_followups(limit=limit)

    def mark_done(self, user_id: int, memory_id: str) -> bool:
        done = self.storage.mark_relationship_done(user_id, memory_id)
        if done:
            self._append_progress_event(
                "relationship_memory_done",
                "关系记忆跟进项已标记完成。",
                {"user_id": user_id, "memory_id": memory_id},
            )
        return done

    def _append_progress_event(self, event_type: str, summary: str, payload: dict) -> None:
        method = getattr(self.storage, "append_progress_event", None)
        if callable(method):
            method(
                {
                    "type": "AutonomyProgressEvent",
                    "source": "relationship",
                    "event_type": event_type,
                    "summary": summary,
                    "payload": payload,
                    "created_at": datetime.now().isoformat(),
                }
            )

    def _append_thought_trace(self, trace_type: str, summary: str, payload: dict) -> None:
        method = getattr(self.storage, "append_thought_trace", None)
        if callable(method):
            method(
                {
                    "type": "ThoughtTrace",
                    "source": "relationship",
                    "trace_type": trace_type,
                    "summary": summary,
                    "payload": payload,
                    "created_at": datetime.now().isoformat(),
                }
            )

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
        normalized = self._normalize_content(content)
        for existing in self.storage.list_relationship_memories(
            user_id, memory_type=memory_type, status="active", limit=50
        ):
            if self._normalize_content(existing.content) == normalized:
                return existing
        memory = self.storage.add_relationship_memory(
            user_id,
            memory_type,
            content,
            source=source,
            confidence=confidence,
            due_at=due_at,
        )
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
        # Relationship memory is private and user-scoped. Keep its dashboard
        # mirror in structured storage instead of the global vector index.
        self.storage.add_note(
            user_id=memory.user_id,
            title=note_title,
            content=note_content,
            category="relationship",
        )

    def _update_mirror_note(self, memory: RelationshipMemory) -> None:
        notes = self.storage.search_notes(memory.user_id, memory.memory_id)
        if notes:
            self.storage.update_note(memory.user_id, notes[0].note_id, memory.content)
            return
        self._sync_note(memory)

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
        profile_lines.append(f"关系阶段: {self.relationship_stage(user_id)}")
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
            (r"我喜欢(.+)", "喜欢"),
            (r"我爱(.+)", "喜欢"),
            (r"我不喜欢(.+)", "不喜欢"),
            (r"我讨厌(.+)", "讨厌"),
        ]
        created: List[RelationshipMemory] = []
        for pattern, attitude in patterns:
            match = re.search(pattern, text)
            if not match:
                continue
            detail = match.group(1).strip("。!！?？ ")
            if not detail:
                continue
            created.append(self._create(user_id, "preference", f"{attitude}：{detail}", confidence=0.85))
            break
        return created

    def _extract_taboos(self, user_id: int, text: str) -> List[RelationshipMemory]:
        patterns = [
            r"别再(.+)",
            r"以后不要(.+)",
            r"请别(.+)",
            r"我不希望你(.+)",
            r"(?:不要|不许)叫我(.+)",
        ]
        created: List[RelationshipMemory] = []
        for pattern in patterns:
            match = re.search(pattern, text)
            if not match:
                continue
            detail = match.group(1).strip("。!！?？ ")
            if not detail:
                continue
            created.append(self._create(user_id, "taboo", detail, confidence=0.9))
            break
        return created

    @staticmethod
    def _normalize_content(content: str) -> str:
        return re.sub(r"[\s。！!？?，,、]", "", content).lower()

    def _extract_promises(self, user_id: int, text: str) -> List[RelationshipMemory]:
        if not any(
            token in text
            for token in ["提醒我", "记得提醒我", "到时候提醒", "回头问我", "之后问我", "帮我跟进"]
        ):
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
