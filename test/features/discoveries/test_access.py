"""Real adapter preprocessing and dispatch, with only transport/data replaced."""
import asyncio
import importlib
from types import SimpleNamespace

import nonebot
from nonebot.adapters.onebot.v11 import (
    Adapter, Bot, GroupMessageEvent, Message, MessageEvent, MessageSegment, PrivateMessageEvent,
)
from nonebot import on_message
import pytest

from src.core.config import Settings
from src.features.discoveries.models import DiscoveryReply
from src.features.discoveries.service import HELP, RepeatGate, parse_command
from src.features.discoveries.journeys import journey
from src.services.governance.service import GovernanceService
from src.services.delivery.dispatcher import OutboundDispatcher
from test.features.discoveries.test_plugin import plugin


def event(message="小鸟", *, private=False):
    values = dict(time=1791250000, self_id=42, post_type="message", user_id=7,
                  message_type="private" if private else "group", sub_type="friend" if private else "normal",
                  message_id=81, message=Message(message), raw_message=str(message), font=0,
                  sender={"user_id": 7, "role": "member"})
    return PrivateMessageEvent(**values) if private else GroupMessageEvent(group_id=12, **values)


class Storage:
    redis = None
    blocked = False

    def is_user_blacklisted(self, user_id):
        return self.blocked

    def is_group_blacklisted(self, group_id):
        return False


@pytest.fixture
def runtime(plugin, monkeypatch):
    state = SimpleNamespace(lookups=[], sends=[], fallback=[], reply_sender=99,
                            settings=Settings(_env_file=None, REDIS_REQUIRED=False, LLM_REQUIRED=False),
                            storage=Storage(), before_result=None)
    governance_module = importlib.import_module("src.services.governance.service")
    delivery = importlib.import_module("src.services.delivery.dispatcher")
    message_runtime = importlib.import_module("nonebot.message")
    monkeypatch.setattr(plugin, "get_settings", lambda: state.settings)
    monkeypatch.setattr(governance_module, "get_settings", lambda: state.settings)
    monkeypatch.setattr(plugin, "_governance", None)
    monkeypatch.setattr(plugin, "GovernanceService", lambda: GovernanceService(state.storage))
    monkeypatch.setattr(plugin, "repeat_gate", RepeatGate())
    state.dispatcher = OutboundDispatcher(spacing=0)
    monkeypatch.setattr(delivery, "dispatch", state.dispatcher.dispatch)
    monkeypatch.setattr(delivery, "observe_group_output", lambda *a: None)

    async def lookup(command, **kwargs):
        state.lookups.append(command)
        if state.before_result:
            await state.before_result()
        return DiscoveryReply("资料 [CQ:at,qq=all]", "https://upload.wikimedia.org/example.jpg")

    async def api(bot, api_name, **kwargs):
        if api_name == "get_msg":
            return dict(time=1791250000, message_type="group", message_id=80, real_id=80,
                        sender={"user_id": state.reply_sender}, message=Message("合成被回复消息"))
        assert api_name in {"send_group_msg", "send_private_msg"}
        state.sends.append(kwargs["message"])
        return {"message_id": 100}

    monkeypatch.setattr(plugin, "service", SimpleNamespace(run=lookup))
    monkeypatch.setattr(Bot, "call_api", api)
    fallback = on_message(priority=40, block=False)

    @fallback.handle()
    async def record_fallback(event: MessageEvent):
        state.fallback.append(event.message_id)

    # Prevent other application matchers from entering a synthetic event test.
    monkeypatch.setattr(message_runtime, "matchers", {10: [plugin.discoveries_handler], 40: [fallback]})
    state.bot = Bot(Adapter(nonebot.get_driver()), "42")
    yield state
    fallback.destroy()


@pytest.mark.asyncio
@pytest.mark.parametrize("private", [False, True])
@pytest.mark.parametrize("command,tool", [
    ("小鸟", "bird"), ("传送", "journey"), ("发表", "journal"), ("/help", "help"),
])
async def test_global_disabled_tools_never_fetch_send_or_fall_back(runtime, private, command, tool):
    runtime.settings.tool_disable_list = "discoveries." + tool
    await runtime.bot.handle_event(event(command, private=private))
    assert not runtime.lookups and not runtime.sends and not runtime.fallback


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["global_omission", "scene_disable", "allowed"])
async def test_global_and_scene_lists_both_apply(runtime, mode):
    runtime.settings.tool_enable_list = "search.web" if mode == "global_omission" else "discoveries.bird"
    if mode == "scene_disable":
        runtime.settings.group_tool_disable_list = "discoveries.bird"
    await runtime.bot.handle_event(event())
    assert len(runtime.lookups) == len(runtime.sends) == (1 if mode == "allowed" else 0)
    assert not runtime.fallback


@pytest.mark.asyncio
@pytest.mark.parametrize("target", [99, 42])
async def test_original_target_survives_reply_preprocessing(runtime, target):
    runtime.reply_sender = target
    original = MessageSegment.reply(80) + MessageSegment.at(target) + " 小鸟"
    message_event = event(original)
    await runtime.bot.handle_event(message_event)
    assert [s.type for s in message_event.original_message] == ["reply", "at", "text"]
    assert [s.type for s in message_event.message] == ["text"]
    assert len(runtime.lookups) == len(runtime.sends) == (1 if target == 42 else 0)
    assert len(runtime.fallback) == (0 if target == 42 else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("message,allowed", [
    ("小鸟", True), (MessageSegment.at(42) + "小鸟", True),
    (MessageSegment.at(99) + "小鸟", False),
    (MessageSegment.image("https://example.com/a.jpg") + "小鸟", False),
])
async def test_real_invocation_and_media_boundaries(runtime, message, allowed):
    await runtime.bot.handle_event(event(message))
    assert len(runtime.lookups) == len(runtime.sends) == int(allowed)
    if allowed:
        assert not runtime.fallback
        assert [s.type for s in runtime.sends[0]] == ["text", "image"]
        assert runtime.sends[0][0].data["text"] == "资料 [CQ:at,qq=all]"


@pytest.mark.asyncio
@pytest.mark.parametrize("private", [False, True])
async def test_revocation_during_lookup_sends_no_result_or_notice(runtime, private):
    async def revoke():
        runtime.storage.blocked = True
    runtime.before_result = revoke
    await runtime.bot.handle_event(event(private=private))
    assert len(runtime.lookups) == 1
    assert not runtime.sends and not runtime.fallback


@pytest.mark.asyncio
async def test_revocation_while_waiting_for_send_position_is_silent(runtime, monkeypatch):
    occupied, release, queued = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def occupy():
        occupied.set()
        await release.wait()
        return True

    blocker = asyncio.create_task(runtime.dispatcher.dispatch("group", 12, occupy, category="reminder"))
    await occupied.wait()
    delivery = importlib.import_module("src.services.delivery.dispatcher")

    async def dispatch(*args, **kwargs):
        queued.set()
        return await runtime.dispatcher.dispatch(*args, **kwargs)

    monkeypatch.setattr(delivery, "dispatch", dispatch)
    command = asyncio.create_task(runtime.bot.handle_event(event()))
    try:
        await asyncio.wait_for(queued.wait(), 2)
        runtime.storage.blocked = True
    finally:
        release.set()
        await asyncio.gather(blocker, command)
    assert len(runtime.lookups) == 1
    assert not runtime.sends and not runtime.fallback


@pytest.mark.asyncio
async def test_failed_final_permission_check_does_not_send(runtime):
    async def break_storage():
        def unavailable(user_id):
            raise OSError("synthetic permission source unavailable")
        runtime.storage.is_user_blacklisted = unavailable
    runtime.before_result = break_storage
    await runtime.bot.handle_event(event())
    assert len(runtime.lookups) == 1
    assert not runtime.sends and not runtime.fallback


def test_help_examples_are_supported_complete_commands():
    assert "敦煌" not in HELP
    for text in ("传送 唐朝", "传送 埃及", "传送 再来"):
        assert text in HELP
        command = parse_command(text)
        assert command is not None
        assert "历史背景：" in journey(command.argument, user_id=321).text
    assert "传送 再来" in journey("火星").text
