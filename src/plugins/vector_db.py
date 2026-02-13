"""Compatibility wrapper for old imports."""

from src.services.vector_store import VectorStore

_store = VectorStore()


def create_db() -> None:
    _store.ensure_index()


def add_to_db(point_text: str) -> None:
    _store.add(point_text)


def search_db(query: str, top_k: int = 3, score_threshold: float = 0.4) -> list[str]:
    return _store.search(query, top_k=top_k, score_threshold=score_threshold)
