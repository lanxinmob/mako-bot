from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.services.chat_engine import ChatEngine, ChatReply, ChatRequest
from src.services.chat_policy import ReplyPlan


class FakeStorage:
    def __init__(self) -> None:
        self.saved = None
        self.records = []

    def get_profile(self, user_id: int):
        return {"profile_text": "喜欢严谨的技术解释"}

    def save_history(self, session_id: str, history: list[dict]) -> None:
        self.saved = (session_id, history)

    def append_global_record(self, record) -> None:
        self.records.append(record)


def make_request(**overrides) -> ChatRequest:
    values = {
        "session_id": "group_42",
        "user_id": 7,
        "nickname": "小明",
        "user_text": "原始消息",
        "llm_text": "原始消息\n\n[联网搜索结果]\n证据",
        "history": [{"role": "assistant", "content": "上一轮"}],
        "message_type": "group",
        "group_id": 42,
        "directed": True,
    }
    values.update(overrides)
    return ChatRequest(**values)


def test_build_messages_composes_canonical_context() -> None:
    engine = ChatEngine(
        storage=FakeStorage(),
        knowledge_search=lambda query: [f"记忆:{query[:4]}"],
    )
    messages = engine._build_messages(make_request())

    assert messages[0]["role"] == "system"
    assert "喜欢严谨的技术解释" in messages[0]["content"]
    assert "记忆:原始消息" in messages[0]["content"]
    assert "Mako 自身档案" in messages[0]["content"]
    assert messages[1] == {"role": "assistant", "content": "上一轮"}
    assert messages[-1]["content"].startswith("【小明_7】：")
    assert "[联网搜索结果]" in messages[-1]["content"]


def test_knowledge_failure_degrades_to_empty_context() -> None:
    def fail(_query: str):
        raise RuntimeError("redis unavailable")

    engine = ChatEngine(storage=FakeStorage(), knowledge_search=fail)
    messages = engine._build_messages(make_request())
    assert "暂无相关长期记忆" in messages[0]["content"]


def test_profile_failure_degrades_to_first_meeting_context() -> None:
    storage = FakeStorage()
    storage.get_profile = lambda _user_id: (_ for _ in ()).throw(RuntimeError("redis down"))
    engine = ChatEngine(storage=storage)
    messages = engine._build_messages(make_request())
    assert "这是首次认识" in messages[0]["content"]


def test_private_vector_memory_is_filtered_by_user_id() -> None:
    engine = ChatEngine(
        storage=FakeStorage(),
        knowledge_search=lambda _query: [
            "[note:8:secret] 别人的私密笔记",
            "[note:7:mine] 当前用户的笔记",
            "[relation:promise:8] 别人的承诺",
            "[relation:promise:7] 已被纠正的旧承诺",
            "[note:7:old] 跟进承诺:old-memory 已被删除的旧承诺",
            "公开知识",
        ],
    )

    messages = engine._build_messages(make_request(user_id=7))
    prompt = messages[0]["content"]

    assert "当前用户的笔记" in prompt
    assert "公开知识" in prompt
    assert "别人的私密笔记" not in prompt
    assert "别人的承诺" not in prompt
    assert "已被纠正的旧承诺" not in prompt
    assert "已被删除的旧承诺" not in prompt


@pytest.mark.asyncio
async def test_generate_returns_uncommitted_reply() -> None:
    storage = FakeStorage()
    engine = ChatEngine(storage=storage)
    engine._call_llm = AsyncMock(return_value=("回复", "fake-model"))

    reply = await engine.generate(make_request())

    assert reply.text == "回复"
    assert reply.model == "fake-model"
    assert reply.history[-1] == {"role": "assistant", "content": "回复"}
    assert storage.saved is None
    assert storage.records == []


@pytest.mark.asyncio
async def test_generate_uses_reply_plan_token_and_character_limits() -> None:
    storage = FakeStorage()
    engine = ChatEngine(storage=storage)
    plan = ReplyPlan(
        mode="micro",
        max_chars=10,
        max_tokens=77,
        latency_min=0.0,
        latency_max=0.0,
    )
    engine._call_llm = AsyncMock(return_value=("第一句。第二句非常非常长。", "fake-model"))

    reply = await engine.generate(make_request(reply_plan=plan, social_state="rapid_exchange"))

    assert len(reply.text) <= 10
    assert reply.text.endswith("…")
    assert engine._call_llm.await_args.kwargs["max_tokens"] == 77
    built_messages = engine._call_llm.await_args.args[0]
    assert "回复硬上限：10 字" in built_messages[0]["content"]
    assert "当前社交状态：rapid_exchange" in built_messages[0]["content"]


def test_commit_persists_only_after_delivery_boundary() -> None:
    storage = FakeStorage()
    engine = ChatEngine(storage=storage)
    request = make_request()
    reply = ChatReply(
        text="已发送",
        history=[{"role": "assistant", "content": "已发送"}],
        model="fake-model",
    )

    engine.commit(request, reply)

    assert storage.saved == ("group_42", reply.history)
    assert len(storage.records) == 1
    assert storage.records[0].role == "assistant"
    assert storage.records[0].content == "已发送"
