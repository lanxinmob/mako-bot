import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from src.services.chat.generation.invocation import GenerationNotAdmitted
from src.services.memory.ledger.runtime import for_storage
from test.memory.ledger.test_records import ledger, isolated_redis, source
from test.chat.generation.test_provider import setup
from test.chat.test_chat_engine import make_request


@pytest.mark.asyncio
async def test_control_committed_after_model_admission_cancels_sdk_entry(ledger, monkeypatch):
    from src.services.chat.generation.invocation import RecordedInvocation
    client = ledger.storage.redis
    mid = (await ledger.mutate(101, 'auto', None, '我喜欢乌龙茶', source(1)))['memory_id']
    sdk, _, engine = setup(monkeypatch, client)
    request = make_request(user_id=101, memory_view=for_storage(ledger.storage, [101]))
    original = RecordedInvocation.call
    async def interleave(self, provider, *args, **kwargs):
        async def after_admission(messages):
            await ledger.mutate(101, 'forget', mid, '', source(2))
            return await provider(messages)
        return await original(self, after_admission, *args, **kwargs)
    monkeypatch.setattr(RecordedInvocation, 'call', interleave)
    with pytest.raises(GenerationNotAdmitted):
        await engine.generate(request)
    sdk.chat.completions.create.assert_not_awaited()
    assert all(m.status == 'forgotten' for m in ledger.list(101))


@pytest.mark.asyncio
async def test_message_construction_finishes_after_control_without_model_call(ledger, monkeypatch):
    import threading
    client = ledger.storage.redis
    mid = (await ledger.mutate(101, 'auto', None, '我喜欢乌龙茶', source(1)))['memory_id']
    sdk, _, engine = setup(monkeypatch, client)
    entered, release = threading.Event(), threading.Event()
    def old_messages(_request, _plan):
        entered.set()
        assert release.wait(3)
        return [{'role': 'user', 'content': '旧正文乌龙茶'}]
    engine._build_messages = old_messages
    task = asyncio.create_task(engine.generate(make_request(user_id=101, memory_view=for_storage(ledger.storage, [101]))))
    assert await asyncio.to_thread(entered.wait, 2)
    await ledger.mutate(101, 'forget', mid, '', source(2))
    release.set()
    with pytest.raises(GenerationNotAdmitted):
        await task
    sdk.chat.completions.create.assert_not_awaited()
