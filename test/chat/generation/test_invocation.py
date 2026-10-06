"""Provider-boundary evidence without network access or paid model calls."""
import asyncio
from datetime import datetime
import json
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.services.chat.generation.invocation import GenerationNotAdmitted, RecordedInvocation
from src.services.persistence.generation.store import GenerationStore
from test.autonomy.test_pending_atomic import isolated_redis


def invoke(store, *, clock=lambda: datetime(2026, 9, 27, 23, 59)):
    return RecordedInvocation(store, input_rate=1, output_rate=2, clock=clock)


async def run(caller, provider, messages=None, phase="reply"):
    return await caller.call(provider, messages or [{"role": "user", "content": "abc"}],
                             user_id=7, phase=phase, model="test", max_output_chars=20)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["offline", "lost_start", "exists"])
async def test_unconfirmed_admission_never_calls_provider(isolated_redis, mode):
    client = isolated_redis
    provider = AsyncMock(return_value="answer")

    def lost(*args):
        client.eval(*args)
        raise ConnectionError("synthetic response loss")

    store = (GenerationStore(None) if mode == "offline" else
             GenerationStore(SimpleNamespace(eval=lost)) if mode == "lost_start" else
             SimpleNamespace(start=lambda spec: None))
    with pytest.raises(GenerationNotAdmitted):
        await run(invoke(store), provider)
    provider.assert_not_awaited()
    if mode == "lost_start":
        key = next(client.scan_iter("mako:generation:v1:*"))
        assert json.loads(client.get(key))["state"] == "calling"


@pytest.mark.asyncio
async def test_each_phase_records_raw_output_and_frozen_day(isolated_redis):
    client = isolated_redis
    caller = invoke(GenerationStore(client))
    ids = []
    for phase in ("reply", "fact_check"):
        provider = AsyncMock(return_value="raw output, before truncation")
        result = await run(caller, provider, phase=phase)
        ids.append(result.attempt_id)
        assert result.cost_status == "recorded"
        value = json.loads(client.get(GenerationStore.key(result.attempt_id)))
        spec = json.loads(value["spec_json"])
        assert spec["phase"] == phase and spec["cost_day"] == "20260927"
        assert json.loads(value["amount_json"]) == pytest.approx(.003 + len(result.text) * .002)
        assert "raw output" not in value["spec_json"]
        provider.assert_awaited_once()
    assert ids[0] != ids[1]


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_failed_or_cancelled_provider_keeps_unknown_without_retry(isolated_redis, cancel):
    client = isolated_redis
    entered = asyncio.Event()

    async def provider(messages):
        entered.set()
        if not cancel:
            raise TimeoutError("synthetic provider timeout")
        await asyncio.Event().wait()

    task = asyncio.create_task(run(invoke(GenerationStore(client)), provider))
    await asyncio.wait_for(entered.wait(), 3)
    if cancel:
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else TimeoutError):
        await task
    keys = list(client.scan_iter("mako:generation:v1:*"))
    assert len(keys) == 1
    value = json.loads(client.get(keys[0]))
    assert value["state"] == "unknown" and value["cost_state"] == "needs_review"
    assert "amount_json" not in value


@pytest.mark.asyncio
async def test_completion_response_loss_preserves_reply_without_reinvocation(isolated_redis):
    client = isolated_redis
    store = GenerationStore(client)

    def lost_complete(spec, token, amount):
        store.complete(spec, token, amount)
        raise ConnectionError("synthetic completion response loss")

    adapter = SimpleNamespace(start=store.start, mark_unknown=store.mark_unknown, complete=lost_complete)
    provider = AsyncMock(return_value="answer")
    result = await run(invoke(adapter), provider)
    assert result.text == "answer" and result.cost_status == "unknown"
    assert json.loads(client.get(store.key(result.attempt_id)))["state"] == "completed"
    provider.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancelled_admission_thread_cannot_later_invoke_provider(isolated_redis):
    client = isolated_redis
    store = GenerationStore(client)
    entered, release, ended = threading.Event(), threading.Event(), threading.Event()

    def delayed_start(spec):
        entered.set()
        try:
            if not release.wait(5):
                raise TimeoutError("test release missing")
            return store.start(spec)
        finally:
            ended.set()

    provider = AsyncMock(return_value="answer")
    task = asyncio.create_task(run(invoke(SimpleNamespace(start=delayed_start)), provider))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
        assert await asyncio.to_thread(ended.wait, 3)
    provider.assert_not_awaited()
    assert len(list(client.scan_iter("mako:generation:v1:*"))) == 1
