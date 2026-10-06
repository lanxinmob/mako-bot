from __future__ import annotations

from src.models.schemas import NoteRecord, RelationshipMemory


def _format_notes(notes: list[NoteRecord]) -> list[dict]:
    return [
        {
            "id": note.note_id,
            "note_id": note.note_id,
            "user_id": note.user_id,
            "title": note.title,
            "content": note.content,
            "category": note.category,
            "visibility": note.visibility,
            "source": "notes",
            "created_at": note.created_at.isoformat(),
            "updated_at": note.updated_at.isoformat(),
        }
        for note in notes
    ]



def _format_long_term_memory(points: list[dict]) -> list[dict]:
    return [
        {
            "id": point.get("id") or f"long-term-{index}",
            "note_id": point.get("id") or f"long-term-{index}",
            "user_id": None,
            "title": point.get("title") or "长期记忆",
            "content": point.get("content") or "",
            "category": point.get("category") or "long_term_memory",
            "visibility": "private",
            "source": point.get("source") or "vector_store",
            "created_at": None,
            "updated_at": None,
        }
        for index, point in enumerate(points)
    ]



def _format_relationship_memory(memory: RelationshipMemory) -> dict:
    return {
        "id": memory.memory_id,
        "memory_id": memory.memory_id,
        "user_id": memory.user_id,
        "type": memory.memory_type,
        "content": memory.content,
        "source": memory.source,
        "status": memory.status,
        "confidence": memory.confidence,
        "created_at": memory.created_at.isoformat(),
        "due_at": memory.due_at.isoformat() if memory.due_at else None,
    }
