from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock

from src.models.schemas import ChatRecord
import src.services.memory.knowledge_precipitation as module


class FakeStorage:
    def __init__(self) -> None:
        self.profile = None
        self.saved = None

    def get_recent_global_records(self, _hours: int):
        return [
            ChatRecord(
                role="user",
                user_id=7,
                nickname="小明",
                content="我长期喜欢乌龙茶",
                time=datetime(2026, 7, 11, 8, 0),
            ),
            ChatRecord(role="assistant", content="记住啦", time=datetime(2026, 7, 11, 8, 1)),
        ]

    def get_profile(self, _user_id: int):
        return self.profile

    def set_profile(self, user_id: int, nickname: str, profile_text: str):
        self.saved = (user_id, nickname, profile_text)


class FakeVectorStore:
    def __init__(self) -> None:
        self.points: list[str] = []

    def add(self, point: str) -> None:
        self.points.append(point)


class FakeCompletions:
    def __init__(self) -> None:
        self.calls = 0

    async def create(self, **_kwargs):
        self.calls += 1
        text = "- 用户 7 长期喜欢乌龙茶" if self.calls == 1 else "【核心特质】稳定\n【行为模式】喜欢乌龙茶"
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


@pytest.mark.asyncio
async def test_daily_precipitation_uses_service_clients_and_persists_results(monkeypatch) -> None:
    storage = FakeStorage()
    vectors = FakeVectorStore()
    completions = FakeCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    monkeypatch.setattr(module, "has_deepseek", lambda: True)
    monkeypatch.setattr(module, "get_deepseek_client", lambda: client)

    result = await module.KnowledgePrecipitationService(storage, vectors).run()

    assert result.records == 2
    assert result.knowledge_points == 1
    assert result.profiles_updated == 1
    assert vectors.points == ["用户 7 长期喜欢乌龙茶"]
    assert storage.saved[0:2] == (7, "小明")


@pytest.mark.asyncio
async def test_daily_batches_cover_more_than_500_records_and_all_speakers(monkeypatch):
    records = [ChatRecord(role="user", user_id=7 if i == 0 else 8,
                          content=f"message-{i}", group_id=1)
               for i in range(501)]
    storage = SimpleNamespace(get_recent_global_records=lambda _hours: records)
    service = module.KnowledgePrecipitationService(storage, FakeVectorStore())
    service._extract_knowledge = AsyncMock(return_value=[])
    service._update_profile = AsyncMock(return_value=True)
    monkeypatch.setattr(module, "has_deepseek", lambda: True)
    result = await service.run()
    processed = [item for call in service._extract_knowledge.call_args_list
                 for item in call.args[0]]
    assert [item.content for item in processed] == [item.content for item in records]
    assert result.records == 501 and result.profiles_updated == 2
    assert [call.args[0] for call in service._update_profile.call_args_list] == [7, 8]


def test_long_message_fragments_preserve_content_and_transcript_budget():
    content = "a" * 30_000
    record = ChatRecord(role="user", user_id=7, group_id=123, nickname="fixture", content=content)
    batches = list(module._record_batches([record]))
    assert len(batches) > 1
    assert "".join(item.content for batch in batches for item in batch) == content
    assert all(len(module._bounded_text(map(module.KnowledgePrecipitationService._format_record, batch)))
               <= 12_000 for batch in batches)


@pytest.mark.asyncio
async def test_empty_profile_response_is_not_counted_as_updated(monkeypatch):
    storage = FakeStorage()
    service = module.KnowledgePrecipitationService(storage, FakeVectorStore())
    service._extract_knowledge = AsyncMock(return_value=[])
    create = AsyncMock(return_value=SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=""))]))
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(module, "has_deepseek", lambda: True)
    monkeypatch.setattr(module, "get_deepseek_client", lambda: client)
    result = await service.run()
    assert result.profiles_updated == 0 and storage.saved is None
