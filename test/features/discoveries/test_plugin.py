from types import SimpleNamespace

import nonebot
from nonebot.adapters.onebot.v11 import Adapter, Message, MessageSegment
import pytest

from src.features.discoveries.models import DiscoveryReply
from src.features.discoveries.service import RepeatGate


@pytest.fixture(scope="module")
def plugin():
    nonebot.init(nickname={"茉子"}, _env_file=None)
    nonebot.get_driver().register_adapter(Adapter)
    loaded = (nonebot.get_plugin("src.plugins.discoveries") or
              nonebot.get_plugin("discoveries") or nonebot.load_plugin("src.plugins.discoveries"))
    assert loaded is not None
    return loaded.module


class Event:
    user_id, group_id, message_type = 7, 12, "group"
    sender = SimpleNamespace(role="member")

    def __init__(self, message):
        self.message = Message(message)

    def get_message(self):
        return self.message

    def get_plaintext(self):
        return self.message.extract_plain_text()


def test_real_registration_and_message_boundaries(plugin):
    assert plugin.discoveries_handler.priority == 10
    assert plugin.discoveries_handler.block
    bot = SimpleNamespace(self_id="42")
    assert plugin.command_for(Event("我看到一只小鸟"), bot) is None
    assert plugin.command_for(Event(MessageSegment.at(99) + "小鸟"), bot) is None
    assert plugin.command_for(Event(MessageSegment.image("https://example.com/a") + "小鸟"), bot) is None
    assert plugin.command_for(Event(MessageSegment.at(42) + " 小鸟"), bot).kind == "bird"
    event = Event("小鸟")
    event.user_id = 42
    assert plugin.command_for(event, bot) is None


@pytest.mark.asyncio
async def test_one_structured_reply_and_duplicates_skip_lookup(plugin, monkeypatch):
    lookups, sends, finishes = [], [], []

    async def run(command, **kwargs):
        lookups.append(command)
        return DiscoveryReply("元数据 [CQ:at,qq=all]", "https://upload.wikimedia.org/a.jpg")

    async def send(bot, target_id, message, **kwargs):
        assert await kwargs.pop("guard")()
        sends.append((message, kwargs))

    async def finish():
        finishes.append(True)

    monkeypatch.setattr(plugin, "_governance", SimpleNamespace(
        tool_allowed=lambda *a, **kw: SimpleNamespace(allowed=True)))
    monkeypatch.setattr(plugin, "service", SimpleNamespace(run=run))
    monkeypatch.setattr(plugin, "repeat_gate", RepeatGate())
    monkeypatch.setattr(plugin, "send_to_group", send)
    matcher, bot = SimpleNamespace(finish=finish), SimpleNamespace(self_id="42")
    await plugin.handle_discovery(matcher, Event("小鸟"), bot)
    await plugin.handle_discovery(matcher, Event("小鸟"), bot)
    await plugin.handle_discovery(matcher, Event("传送"), bot)
    assert len(lookups) == len(sends) == 2
    assert len(finishes) == 3
    message, kwargs = sends[0]
    assert [segment.type for segment in message] == ["text", "image"]
    assert message[0].data["text"] == "元数据 [CQ:at,qq=all]"
    assert kwargs == {"category": "command"}


@pytest.mark.asyncio
async def test_denied_tools_do_not_lookup_or_send(plugin, monkeypatch):
    async def forbidden(*args, **kwargs):
        pytest.fail("permission denied must not fetch or send")

    async def finish():
        pass

    monkeypatch.setattr(plugin, "_governance", SimpleNamespace(
        tool_allowed=lambda *a, **kw: SimpleNamespace(allowed=False)))
    monkeypatch.setattr(plugin, "service", SimpleNamespace(run=forbidden))
    monkeypatch.setattr(plugin, "send_to_group", forbidden)
    monkeypatch.setattr(plugin, "send_to_private", forbidden)
    await plugin.handle_discovery(SimpleNamespace(finish=finish), Event("期刊 Nature"),
                                  SimpleNamespace(self_id="42"))
