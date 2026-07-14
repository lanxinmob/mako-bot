from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from src.models.schemas import ChatRecord
from src.services import knowledge_precipitation as module


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
