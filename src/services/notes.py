from __future__ import annotations

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
        return note

    def list_notes(self, user_id: int) -> List[NoteRecord]:
        return self.storage.list_notes(user_id)

    def search_notes(self, user_id: int, keyword: str) -> List[NoteRecord]:
        return self.storage.search_notes(user_id, keyword)

    def delete_note(self, user_id: int, note_id_or_keyword: str) -> bool:
        return self.storage.delete_note(user_id, note_id_or_keyword)

    def update_note(self, user_id: int, note_id_or_keyword: str, content: str) -> Optional[NoteRecord]:
        updated = self.storage.update_note(user_id, note_id_or_keyword, content)
        if updated:
            self.vector_store.add(f"[note:{user_id}:{updated.note_id}] {updated.title} {updated.content}")
        return updated
