from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from src.models.schemas import NoteRecord
from src.services.storage import StorageService
from src.services.vector_store import VectorStore


class NoteService:
    def __init__(self) -> None:
        self.storage = StorageService()
        self.vector_store = VectorStore()

    def add_note(self, user_id: int, title: str, content: str, category: str = "default") -> NoteRecord:
        note = self.storage.add_note(user_id=user_id, title=title, content=content, category=category)
        self.vector_store.add(f"[note:{user_id}:{note.note_id}] {title} {content}")
        self._append_progress_event(
            "note_created",
            "笔记已创建并写入向量索引。",
            {
                "user_id": user_id,
                "note_id": note.note_id,
                "title": title,
                "category": category,
                "content_preview": content[:160],
            },
        )
        self._append_thought_trace(
            "note_write_summary",
            "笔记写入完成；仅保存标题、分类和内容摘要，不保存隐藏推理链。",
            {
                "user_id": user_id,
                "note_id": note.note_id,
                "title": title,
                "category": category,
                "content_preview": content[:160],
            },
        )
        return note

    def list_notes(self, user_id: int) -> List[NoteRecord]:
        return self.storage.list_notes(user_id)

    def search_notes(self, user_id: int, keyword: str) -> List[NoteRecord]:
        return self.storage.search_notes(user_id, keyword)

    def delete_note(self, user_id: int, note_id_or_keyword: str) -> bool:
        deleted = self.storage.delete_note(user_id, note_id_or_keyword)
        if deleted:
            self._append_progress_event(
                "note_deleted",
                "笔记已删除。",
                {"user_id": user_id, "note_id_or_keyword": note_id_or_keyword},
            )
        return deleted

    def update_note(self, user_id: int, note_id_or_keyword: str, content: str) -> Optional[NoteRecord]:
        updated = self.storage.update_note(user_id, note_id_or_keyword, content)
        if updated:
            self.vector_store.add(f"[note:{user_id}:{updated.note_id}] {updated.title} {updated.content}")
            self._append_progress_event(
                "note_updated",
                "笔记已更新并写入向量索引。",
                {
                    "user_id": user_id,
                    "note_id": updated.note_id,
                    "title": updated.title,
                    "content_preview": content[:160],
                },
            )
            self._append_thought_trace(
                "note_update_summary",
                "笔记更新完成；仅保存更新摘要，不保存隐藏推理链。",
                {
                    "user_id": user_id,
                    "note_id": updated.note_id,
                    "title": updated.title,
                    "content_preview": content[:160],
                },
            )
        return updated

    def _append_progress_event(self, event_type: str, summary: str, payload: dict) -> None:
        method = getattr(self.storage, "append_progress_event", None)
        if callable(method):
            method(
                {
                    "type": "AutonomyProgressEvent",
                    "source": "notes",
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
                    "source": "notes",
                    "trace_type": trace_type,
                    "summary": summary,
                    "payload": payload,
                    "created_at": datetime.now().isoformat(),
                }
            )
