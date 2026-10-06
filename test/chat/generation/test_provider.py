"""Actual provider adapter and ChatEngine paths with a synthetic SDK only."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.services.chat.engine import ChatEngine
from src.services.chat.generation import provider
from src.services.chat.generation.discovery import GenerationCostScanner
from src.services.chat.generation.invocation import GenerationNotAdmitted
from src.services.retrieval.models import SearchOutcome
from test.autonomy.test_pending_atomic import isolated_redis
from test.chat.test_chat_engine import FakeStorage, make_request


def setup(monkeypatch, client, outputs=(" answer ",)):
    sdk = Mock()
    sdk.with_options.return_value = sdk
    sdk.chat.completions.create = AsyncMock(side_effect=[
        SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))]) for text in outputs])
    factory = Mock(return_value=sdk)
    monkeypatch.setattr(provider, "has_deepseek", lambda: False)
    monkeypatch.setattr(provider, "has_openai", lambda: True)
    monkeypatch.setattr(provider, "get_openai_client", factory)
    storage = FakeStorage()
    storage.redis = client
    engine = ChatEngine(storage=storage)
    engine.settings = SimpleNamespace(llm_cost_per_1k_chars_input=1, llm_cost_per_1k_chars_output=2)
    engine._build_messages = lambda request, plan: [{"role": "user", "content": "abc"}]
    return sdk, factory, engine


@pytest.mark.asyncio
async def test_engine_provider_persists_before_call_and_disables_sdk_retries(isolated_redis, monkeypatch):
    client = isolated_redis
    sdk, _, engine = setup(monkeypatch, client)
    create = sdk.chat.completions.create

    async def checked(**kwargs):
        keys = list(client.scan_iter("mako:generation:v1:*"))
        assert len(keys) == 1 and json.loads(client.get(keys[0]))["state"] == "calling"
        return await create(**kwargs)

    sdk.chat.completions.create = AsyncMock(side_effect=checked)
    reply = await engine.generate(make_request())
    assert reply.text == "answer" and reply.cost_status == "complete"
    sdk.with_options.assert_called_once_with(max_retries=0)
    key = next(client.scan_iter("mako:generation:v1:*"))
    raw = json.loads(client.get(key))
    assert raw["cost_state"] == "complete"
    day = json.loads(raw["spec_json"])["cost_day"]
    assert float(client.get("cost:global:" + day)) == pytest.approx(.003 + .002 * len(" answer "))


@pytest.mark.asyncio
async def test_redis_offline_prevents_even_sdk_client_creation(monkeypatch):
    _, factory, engine = setup(monkeypatch, None)
    with pytest.raises(GenerationNotAdmitted):
        await engine.generate(make_request())
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_fact_check_is_a_separate_tracked_invocation(isolated_redis, monkeypatch):
    client = isolated_redis
    sdk, _, engine = setup(monkeypatch, client, outputs=("answer", '{"consistent":true}'))
    outcome = SearchOutcome(required=True, success=True, factual_mode=True, realtime=False)
    reply = await engine.generate(make_request(search_outcome=outcome))
    assert reply.cost_status == "complete" and sdk.chat.completions.create.await_count == 2
    records = [json.loads(client.get(key)) for key in client.scan_iter("mako:generation:v1:*")]
    assert {json.loads(value["spec_json"])["phase"] for value in records} == {"reply", "fact_check"}
    assert all(value["cost_state"] == "complete" for value in records)


@pytest.mark.asyncio
async def test_deferred_cost_is_discovered_without_second_provider_call(isolated_redis, monkeypatch):
    client = isolated_redis
    sdk, _, engine = setup(monkeypatch, client)
    monkeypatch.setattr(provider, "GenerationCostWorker", lambda client: SimpleNamespace(
        run=AsyncMock(side_effect=ConnectionError("synthetic outage"))))
    reply = await engine.generate(make_request())
    assert reply.cost_status == "pending"
    assert not list(client.scan_iter("cost:*"))
    await GenerationCostScanner(client).run_page()
    assert list(client.scan_iter("cost:*"))
    sdk.chat.completions.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_no_provider_does_not_create_billable_attempt(isolated_redis, monkeypatch):
    client = isolated_redis
    _, factory, engine = setup(monkeypatch, client)
    monkeypatch.setattr(provider, "has_openai", lambda: False)
    reply = await engine.generate(make_request())
    assert reply.model == "fallback" and reply.cost_status == "complete"
    assert not list(client.scan_iter())
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_deepseek_vision_receives_image_parts_in_one_sdk_request(isolated_redis, monkeypatch):
    client = isolated_redis
    sdk, factory, engine = setup(monkeypatch, client)
    monkeypatch.setattr(provider, "has_deepseek", lambda: True)
    monkeypatch.setattr(provider, "get_deepseek_client", factory)
    monkeypatch.setattr(provider, "get_deepseek_model", lambda: "deepseek-v4-flash-vision")
    image = "data:image/png;base64,c3ludGhldGlj"
    messages = [{"role": "user", "content": [
        {"type": "text", "text": "看图"}, {"type": "image_url", "image_url": {"url": image}}]}]
    engine._build_messages = lambda request, plan: messages
    reply = await engine.generate(make_request())
    assert reply.model == "deepseek-v4-flash-vision"
    sdk.chat.completions.create.assert_awaited_once()
    kwargs = sdk.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == reply.model and kwargs["messages"] == messages
    assert image not in str([client.get(key) for key in client.scan_iter("mako:generation:v1:*")])
