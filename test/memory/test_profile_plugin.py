"""Real QQ routing with synthetic profiles and transport only."""
import asyncio
import importlib
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import nonebot
import pytest
from nonebot import on_message
from nonebot.adapters.onebot.v11 import Adapter, Bot, MessageEvent, MessageSegment

from src.features.discoveries.service import HELP, RepeatGate
from src.services.delivery.dispatcher import OutboundDispatcher
from src.services.memory.profile_view import ProfileViewService
from test.features.discoveries.test_access import event
from test.features.discoveries.test_plugin import plugin


@pytest.fixture
def runtime(plugin, monkeypatch):
    storage_module = importlib.import_module("src.services.persistence")
    # Profile routing needs neither the embedding runtime nor the daily model job.
    knowledge = ModuleType("src.services.memory.knowledge_precipitation")
    knowledge.KnowledgePrecipitationService = lambda: SimpleNamespace()
    monkeypatch.setattr(storage_module, "StorageService", Mock)
    monkeypatch.setitem(sys.modules, knowledge.__name__, knowledge)
    loaded = (nonebot.get_plugin("precipitate_knowledge") or
              nonebot.load_plugin("src.plugins.precipitate_knowledge"))
    assert loaded is not None
    module = loaded.module
    state = SimpleNamespace(owner=7, sends=[], fallback=[], module=module, storage=Mock())
    state.storage.list_profiles.return_value = [dict(user_id=42, nickname="小明",
        profile_text="完整合成档案 [CQ:at,qq=all]", last_updated="2026-10-07")]
    state.storage.get_profile.return_value = state.storage.list_profiles.return_value[0]
    monkeypatch.setattr(module, "get_settings", lambda: SimpleNamespace(autonomy_owner_id=state.owner))
    monkeypatch.setattr(module, "profile_view", ProfileViewService(state.storage))
    monkeypatch.setattr(module, "profile_gate", RepeatGate())
    delivery = importlib.import_module("src.services.delivery.dispatcher")
    state.dispatcher = OutboundDispatcher(spacing=0)
    monkeypatch.setattr(delivery, "dispatch", state.dispatcher.dispatch)
    monkeypatch.setattr(delivery, "observe_plugin_output", lambda *a: None)

    async def api(bot, name, **kwargs):
        assert name == "send_private_msg"
        state.sends.append(kwargs)
        return {"message_id": 101}

    monkeypatch.setattr(Bot, "call_api", api)
    fallback = on_message(priority=40, block=False)

    @fallback.handle()
    async def record_fallback(event: MessageEvent):
        state.fallback.append(event.message_id)

    message_runtime = importlib.import_module("nonebot.message")
    monkeypatch.setattr(message_runtime, "matchers", {9: [module.memory_handler], 40: [fallback]})
    state.bot = Bot(Adapter(nonebot.get_driver()), "42")
    yield state
    fallback.destroy()


@pytest.mark.asyncio
@pytest.mark.parametrize("private", [False, True])
@pytest.mark.parametrize("command", ["人物档案", "人物档案 42", "人物档案 小明", "/memory 42"])
async def test_owner_receives_only_private_structured_output(runtime, private, command):
    await runtime.bot.handle_event(event(command, private=private))
    assert len(runtime.sends) == 1 and not runtime.fallback
    assert runtime.sends[0]["user_id"] == 7
    message = runtime.sends[0]["message"]
    assert [segment.type for segment in message] == ["text"]
    text = message.extract_plain_text()
    assert ("1 人" in text if command == "人物档案" else "完整合成档案 [CQ:at,qq=all]" in text)


@pytest.mark.asyncio
@pytest.mark.parametrize("owner", [None, 0, 8])
@pytest.mark.parametrize("command", ["人物档案 42", "可塑性记忆 42", "/memory 42"])
async def test_unauthorized_and_unconfigured_owner_are_silent_without_reads(runtime, owner, command):
    runtime.owner = owner
    await runtime.bot.handle_event(event(command, private=True))
    assert not runtime.storage.mock_calls and not runtime.sends and not runtime.fallback


@pytest.mark.asyncio
async def test_owner_revocation_while_queued_prevents_disclosure(runtime, monkeypatch):
    occupied, release, queued = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def hold():
        occupied.set()
        await release.wait()
        return True

    delivery = importlib.import_module("src.services.delivery.dispatcher")

    async def dispatch(*args, **kwargs):
        queued.set()
        return await runtime.dispatcher.dispatch(*args, **kwargs)

    blocker = asyncio.create_task(runtime.dispatcher.dispatch("private", 7, hold, category="command"))
    await occupied.wait()
    monkeypatch.setattr(delivery, "dispatch", dispatch)
    command = asyncio.create_task(runtime.bot.handle_event(event("人物档案 42", private=True)))
    try:
        await asyncio.wait_for(queued.wait(), 2)
        runtime.owner = 8
    finally:
        release.set()
        await asyncio.gather(blocker, command)
    assert runtime.storage.get_profile.call_count == 1
    assert not runtime.sends and not runtime.fallback


@pytest.mark.asyncio
async def test_other_mentions_do_not_claim_commands(runtime):
    await runtime.bot.handle_event(event(MessageSegment.at(99) + "人物档案 42"))
    assert not runtime.storage.mock_calls and not runtime.sends
    assert runtime.fallback


def test_help_describes_owner_only_profile_commands():
    assert "人物档案 ID" in HELP and "人物档案 名称" in HELP
    assert "仅 owner" in HELP and "私聊给你" in HELP
