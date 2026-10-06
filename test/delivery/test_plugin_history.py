"""Plugin ACKs remain visible without evicting ordinary dialogue."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from test.autonomy.test_pending_atomic import isolated_redis
from src.core.config import Settings
from src.services.chat.engine import ChatEngine
from src.services.chat.models import ChatRequest
from src.services.delivery import dispatcher, observation
from src.services.persistence import StorageService
from src.services.persistence.backends import StorageBackend
from src.services.persistence.backends.memory import MemoryStorage
from src.services.persistence.plugin_history import PluginHistoryRepository


def backend(client):
    result = StorageBackend(Settings(max_history_turns=20), initialize=False)
    result.redis = client
    result.memory = MemoryStorage()
    return result


def entry(index, text=None):
    return {"role": "assistant", "content": text or f"plugin {index}",
            "message_id": str(index), "category": "command", "sent_at_ms": 1000 + index}


def storage_for(client):
    storage = StorageService.__new__(StorageService)
    storage._backend = backend(client)
    return storage


def test_concurrent_plugin_writes_keep_chat_turns_and_survive_restart(isolated_redis):
    storage = storage_for(isolated_redis)
    ordinary = [{"role": role, "content": f"chat {i} {role}"}
                for i in range(20) for role in ("user", "assistant")]
    storage.save_history("private_7", ordinary)
    repository = PluginHistoryRepository(storage.backend)

    def write(index):
        repository.remember("9", "private_7", entry(index))
        repository.persist("9", "private_7", entry(index))

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(write, reversed(range(1, 61))))
    repository.persist("9", "private_7", entry(60))  # Duplicate ACK.
    assert storage.get_history("private_7") == ordinary
    restored = storage_for(isolated_redis)
    assert [int(row["message_id"]) for row in restored.get_plugin_history("private_7", "9")] == list(range(41, 61))
    for bot_id, session in (("8", "private_7"), ("9", "private_8"), ("9", "group_7")):
        assert restored.get_plugin_history(session, bot_id) == []


@pytest.mark.asyncio
async def test_acknowledged_card_reaches_prompt_and_search_but_not_chat_history(isolated_redis, monkeypatch):
    storage = storage_for(isolated_redis)
    repository = PluginHistoryRepository(storage.backend)
    monkeypatch.setattr(observation, "_plugin_history_repository", lambda: repository)
    monkeypatch.setattr(dispatcher, "_configured", True)
    monkeypatch.setattr(dispatcher, "outbound", dispatcher.OutboundDispatcher(spacing=0))
    bot = SimpleNamespace(self_id="9", send_private_msg=AsyncMock(return_value={"message_id": 501}))
    card = "Tactile robotics: Past and future\nhttps://doi.org/10.1177/02783649261421615"
    assert await dispatcher.send_to_private(bot, 7, card)
    # Immediate context is available even before background persistence completes.
    rows = storage.get_plugin_history("private_7", "9")
    request = ChatRequest("private_7", 7, "小明", "这几篇讲了什么", "这几篇讲了什么", [], plugin_history=rows)
    engine = ChatEngine(storage=storage, knowledge_search=lambda _: [])
    prompt = engine._build_messages(request)[0]["content"]
    assert card in prompt and "已发送" in prompt
    assert "只有标题和链接时" in prompt
    assert engine._next_history(request, "先读取摘要") == [
        {"role": "user", "content": "这几篇讲了什么"}, {"role": "assistant", "content": "先读取摘要"}]
    await asyncio.gather(*tuple(observation._history_tasks))
    assert storage_for(isolated_redis).get_plugin_history("private_7", "9")[0]["content"] == card


@pytest.mark.asyncio
@pytest.mark.parametrize("result,category,expected", [({}, "command", False),
    (False, "command", False), ({"message_id": 502}, "chat", False),
    ({"message_id": 502}, "command", True)])
async def test_failed_persistence_does_not_resend_or_invent_delivery(monkeypatch, result, category, expected):
    storage = storage_for(None)
    repository = PluginHistoryRepository(storage.backend)
    monkeypatch.setattr(observation, "_plugin_history_repository", lambda: repository)
    monkeypatch.setattr(dispatcher, "_configured", True)
    monkeypatch.setattr(dispatcher, "outbound", dispatcher.OutboundDispatcher(spacing=0))
    bot = SimpleNamespace(self_id="9", send_private_msg=AsyncMock(return_value=result))
    sent = await dispatcher.send_to_private(bot, 7, "card", category=category)
    await asyncio.gather(*tuple(observation._history_tasks))
    assert bool(storage.get_plugin_history("private_7", "9")) == expected
    assert sent == (isinstance(result, dict) and "message_id" in result)
    bot.send_private_msg.assert_awaited_once()
