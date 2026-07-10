from __future__ import annotations

from src.services.relationship import RelationshipService
from src.services.storage import StorageService


def test_relationship_memory_is_user_scoped_correctable_and_deletable() -> None:
    storage = StorageService()
    storage.redis = None
    service = RelationshipService(storage=storage)
    owner_id = 910001
    other_id = 910002

    created = service.absorb_user_message(owner_id, "小明", "我喜欢乌龙茶")

    assert len(created) == 1
    memory = created[0]
    assert memory.content == "喜欢：乌龙茶"
    assert storage.list_relationship_memories(other_id, status="", limit=20) == []
    assert service.correct_memory(
        other_id, memory.memory_id, "喜欢：咖啡", nickname="别人"
    ) is None

    updated = service.correct_memory(
        owner_id, memory.memory_id, "喜欢：红茶", nickname="小明"
    )
    assert updated is not None
    assert updated.content == "喜欢：红茶"
    assert "喜欢：红茶" in service.format_memories(owner_id)

    assert service.delete_memory(owner_id, memory.memory_id, nickname="小明")
    assert storage.get_relationship_memory(owner_id, memory.memory_id) is None


def test_duplicate_relationship_statement_does_not_create_another_memory() -> None:
    storage = StorageService()
    storage.redis = None
    service = RelationshipService(storage=storage)
    user_id = 910003

    first = service.absorb_user_message(user_id, "小夏", "我喜欢散步")
    second = service.absorb_user_message(user_id, "小夏", "我喜欢散步。")

    assert len(first) == 1
    assert second == []
    assert len(storage.list_relationship_memories(user_id, status="active", limit=20)) == 1


def test_transient_instruction_is_not_saved_as_a_taboo() -> None:
    storage = StorageService()
    storage.redis = None
    service = RelationshipService(storage=storage)
    user_id = 910004

    created = service.absorb_user_message(user_id, "小李", "不要搜索，直接解释这段代码")

    assert [memory for memory in created if memory.memory_type == "taboo"] == []
