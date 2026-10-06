from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import List, Optional

from src.models.schemas import NoteRecord


from src.services.persistence.backends import Repository


class NotesRepository(Repository):
    def add_note(
        self,
        user_id: int,
        title: str,
        content: str,
        category: str = "default",
        visibility: str = "private",
    ) -> NoteRecord:
        note = NoteRecord(
            note_id=uuid.uuid4().hex[:10],
            user_id=user_id,
            title=title,
            content=content,
            category=category,
            visibility=visibility,  # type: ignore[arg-type]
        )
        key = f"notes:{user_id}"
        if self.redis:
            self.redis.hset(key, note.note_id, json.dumps(note.model_dump(mode="json"), ensure_ascii=False))
            return note
        self.backend.memory.notes.setdefault(user_id, {})[note.note_id] = note.model_dump(mode="json")
        return note

    def list_notes(self, user_id: int) -> List[NoteRecord]:
        if self.redis:
            raw = self.redis.hvals(f"notes:{user_id}")
            result: List[NoteRecord] = []
            for item in raw:
                try:
                    result.append(NoteRecord.model_validate_json(item))
                except Exception:
                    continue
            result.sort(key=lambda x: x.updated_at, reverse=True)
            return result
        data = self.backend.memory.notes.get(user_id, {})
        notes = [NoteRecord.model_validate(item) for item in data.values()]
        notes.sort(key=lambda x: x.updated_at, reverse=True)
        return notes

    def list_all_notes(self, limit: int = 200) -> List[NoteRecord]:
        notes: List[NoteRecord] = []
        if self.redis:
            for key in self.redis.keys("notes:*"):
                for item in self.redis.hvals(key):
                    try:
                        notes.append(NoteRecord.model_validate_json(item))
                    except Exception:
                        continue
        else:
            for user_notes in self.backend.memory.notes.values():
                for item in user_notes.values():
                    try:
                        notes.append(NoteRecord.model_validate(item))
                    except Exception:
                        continue
        notes.sort(key=lambda x: x.updated_at, reverse=True)
        return notes[:limit]

    def list_long_term_memory_points(self, limit: int = 200) -> List[dict]:
        if not self.redis:
            return []
        points: List[dict] = []
        try:
            keys = self.redis.keys(f"{self.settings.vector_prefix}*")
        except Exception:
            return []
        for key in keys[:limit]:
            try:
                text = self.redis.hget(key, "point_text")
            except Exception:
                continue
            if not text:
                continue
            points.append(
                {
                    "id": str(key).removeprefix(self.settings.vector_prefix),
                    "title": "长期记忆",
                    "content": text,
                    "category": "long_term_memory",
                    "source": "vector_store",
                }
            )
        return points

    def search_notes(self, user_id: int, keyword: str) -> List[NoteRecord]:
        notes = self.list_notes(user_id)
        keyword_lower = keyword.lower()
        return [
            n for n in notes if keyword_lower in n.title.lower() or keyword_lower in n.content.lower()
        ]

    def delete_note(self, user_id: int, note_id_or_keyword: str) -> bool:
        key = f"notes:{user_id}"
        target_id = note_id_or_keyword

        if not target_id:
            return False
        notes = self.list_notes(user_id)
        if target_id not in {n.note_id for n in notes}:
            for note in notes:
                if target_id in note.title or target_id in note.content:
                    target_id = note.note_id
                    break

        if self.redis:
            return bool(self.redis.hdel(key, target_id))
        user_notes = self.backend.memory.notes.get(user_id, {})
        return user_notes.pop(target_id, None) is not None

    def update_note(self, user_id: int, note_id_or_keyword: str, new_content: str) -> Optional[NoteRecord]:
        notes = self.list_notes(user_id)
        target: Optional[NoteRecord] = None
        for note in notes:
            if note.note_id == note_id_or_keyword or note_id_or_keyword in note.title:
                target = note
                break
        if not target:
            return None
        target.content = new_content
        target.updated_at = datetime.now()
        key = f"notes:{user_id}"
        if self.redis:
            self.redis.hset(
                key,
                target.note_id,
                json.dumps(target.model_dump(mode="json"), ensure_ascii=False),
            )
            return target
        self.backend.memory.notes.setdefault(user_id, {})[target.note_id] = target.model_dump(mode="json")
        return target
