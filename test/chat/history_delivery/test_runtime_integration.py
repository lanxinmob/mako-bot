"""Real plan/send/consumer integration uses synthetic QQ ACKs and isolated Redis."""
import asyncio
import importlib.util
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from nonebot.adapters.onebot.v11 import GroupMessageEvent
import pytest

from src.services.chat.context import EnrichedChatInput
from src.services.chat.history_delivery.runtime import ChatHistoryRuntime, HistoryNotAdmitted
from src.services.chat.models import ChatReply
from src.services.chat.pipeline import execution
from src.services.chat.pipeline.models import ChatInput, ChatServices
from src.services.chat.policy import ChatAddress
from src.services.delivery.dispatcher import OutboundDispatcher
from src.services.persistence.effects import EffectUnavailable
from src.services.persistence.history_commit.delivery import HistoryDeliveryStore
from src.services.chat.history_delivery.discovery import HistoryScanner
from src.services.tools.models import ToolExecutionResult
from src.utils.message import NormalizedMessage
from test.autonomy.test_pending_atomic import isolated_redis


@pytest.fixture
def setup_runtime(isolated_redis, monkeypatch):
    client = isolated_redis
    source = ' [ {"role":"user", "content":"old"} ] '
    client.set("chat:history:group_8", source)
    plan = SimpleNamespace(max_chars=80, mode="short", social_state="normal")
    monkeypatch.setattr(execution, "select_reply_plan", lambda *_a, **_k: plan)
    monkeypatch.setattr(execution, "remaining_reply_delay", lambda *_a: 0)
    monkeypatch.setattr(execution, "decide_intents", lambda *_a, **_k: [])
    tools = SimpleNamespace(run=AsyncMock(return_value=ToolExecutionResult()), cleanup_temp_files=Mock())
    storage = SimpleNamespace(redis=client, get_history=Mock(side_effect=AssertionError("legacy read forbidden")))

    async def generate(request):
        assert request.history_snapshot.raw == source.encode("utf-8")
        assert request.history == [{"role": "user", "content": "old"}]
        return ChatReply("new reply", request.history + [{"role": "assistant", "content": "new reply"}],
                         "synthetic", cost_status="complete")

    services = ChatServices(
        SimpleNamespace(max_history_turns=2, global_memory_max_records=1000), storage,
        Mock(), SimpleNamespace(build=AsyncMock(return_value=EnrichedChatInput("hello", "hello"))),
        Mock(), SimpleNamespace(estimate_llm_cost=Mock(return_value=0),
                               can_consume_cost=Mock(return_value=SimpleNamespace(allowed=True)), consume_cost=Mock()),
        Mock(), SimpleNamespace(generate=AsyncMock(side_effect=generate), commit=Mock()), lambda: tools)
    path = Path(__file__).resolve().parents[3] / "src/plugins/chat/delivery.py"
    spec = importlib.util.spec_from_file_location("history_qq_delivery", path)
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    adapter.dispatch = OutboundDispatcher(spacing=0).dispatch
    matcher = SimpleNamespace(send=AsyncMock(return_value={"message_id": 42}))
    bot = SimpleNamespace(get_group_member_list=AsyncMock(return_value=[]))
    event = GroupMessageEvent.model_construct(group_id=8, user_id=7, message_id=9)

    async def recorded(text, *, before_send, on_ack):
        return await adapter.send_reply(matcher, event, bot, text, before_send=before_send, on_ack=on_ack)

    transport = SimpleNamespace(reply_recorded=recorded, notice=AsyncMock(), extra=AsyncMock(return_value=True))
    incoming = ChatInput(ChatAddress("group", 7, 8), "fixture", "hello", NormalizedMessage(),
                         True, False, 0, "99")
    return client, services, incoming, transport, tools, matcher


def one_record(client):
    keys = client.keys("mako:chat:delivery:v1:*")
    assert len(keys) == 1
    return keys[0], json.loads(client.get(keys[0]))


@pytest.mark.asyncio
async def test_actual_pipeline_activates_and_consumes_frozen_history_once(setup_runtime):
    client, services, incoming, transport, tools, matcher = setup_runtime
    await execution.execute(services, incoming, transport, tools, None)
    key, data = one_record(client)
    assert data["state"] == "sent" and data["tasks"] == {"session": "complete", "global": "complete"}
    assert client.ttl(key) == -1 and client.llen("all_memory") == 1
    assert json.loads(client.get("chat:history:group_8"))[-1]["content"] == "new reply"
    matcher.send.assert_awaited_once()
    services.chat_engine.commit.assert_not_called()
    services.storage.get_history.assert_not_called()
    services.governance.consume_cost.assert_not_called()
    assert services.audit.progress.call_args.args[2]["history"] == "confirmed"
    tools.cleanup_temp_files.assert_called_once()


@pytest.mark.asyncio
async def test_no_qq_ack_keeps_history_dormant_without_replay(setup_runtime):
    client, services, incoming, transport, tools, matcher = setup_runtime
    matcher.send.return_value = None
    before = client.dump("chat:history:group_8")
    await execution.execute(services, incoming, transport, tools, None)
    key, data = one_record(client)
    assert data["state"] == "unknown" and data["tasks"] == {"session": "dormant", "global": "dormant"}
    assert client.dump("chat:history:group_8") == before and not client.exists("all_memory")
    matcher.send.assert_awaited_once()
    identity = key.rsplit(":", 1)[1]
    assert HistoryDeliveryStore(client).transition(identity, data["token"], "begin") == "denied"


@pytest.mark.asyncio
async def test_plan_failure_pauses_send_after_generation_cost_was_observed(setup_runtime, monkeypatch):
    from src.services.chat.history_delivery import runtime
    client, services, incoming, transport, tools, matcher = setup_runtime

    class BrokenStore(HistoryDeliveryStore):
        def create(self, plan):
            raise EffectUnavailable("synthetic plan outage")

    monkeypatch.setattr(runtime, "HistoryDeliveryStore", BrokenStore)
    await execution.execute(services, incoming, transport, tools, None)
    services.chat_engine.generate.assert_awaited_once()
    matcher.send.assert_not_awaited()
    transport.notice.assert_awaited_once()
    assert services.audit.progress.call_args.args[2]["cost"] == "complete"
    assert not client.keys("mako:chat:delivery:v1:*") and not client.exists("all_memory")


@pytest.mark.asyncio
async def test_bad_snapshot_pauses_before_tools_and_model(setup_runtime):
    client, services, incoming, transport, tools, matcher = setup_runtime
    client.set("chat:history:group_8", "invalid-json")
    await execution.execute(services, incoming, transport, tools, None)
    services.chat_engine.generate.assert_not_awaited()
    tools.run.assert_not_awaited()
    matcher.send.assert_not_awaited()
    transport.notice.assert_awaited_once()
    assert client.get("chat:history:group_8") == "invalid-json"


@pytest.mark.asyncio
async def test_begin_response_loss_never_calls_qq(setup_runtime, monkeypatch):
    from src.services.chat.history_delivery import runtime
    client, services, incoming, transport, tools, matcher = setup_runtime

    class LostBegin(HistoryDeliveryStore):
        def transition(self, identity, token, operation, **kwargs):
            result = super().transition(identity, token, operation, **kwargs)
            if operation == "begin":
                raise EffectUnavailable("synthetic begin response loss")
            return result

    monkeypatch.setattr(runtime, "HistoryDeliveryStore", LostBegin)
    await execution.execute(services, incoming, transport, tools, None)
    _, data = one_record(client)
    assert data["state"] == "unknown" and data["tasks"] == {"session": "dormant", "global": "dormant"}
    matcher.send.assert_not_awaited()
    assert not client.exists("all_memory")


@pytest.mark.asyncio
async def test_candidate_invalidated_during_begin_is_not_sent(setup_runtime, monkeypatch):
    from src.services.chat.history_delivery import runtime
    client, services, incoming, transport, tools, matcher = setup_runtime
    current = [True]

    class InvalidatedBegin(HistoryDeliveryStore):
        def transition(self, identity, token, operation, **kwargs):
            result = super().transition(identity, token, operation, **kwargs)
            if operation == "begin":
                current[0] = False
            return result

    monkeypatch.setattr(runtime, "HistoryDeliveryStore", InvalidatedBegin)
    await execution.execute(services, replace(incoming, is_current=lambda: current[0]), transport, tools, None)
    _, data = one_record(client)
    assert data["state"] == "unknown" and data["tasks"] == {"session": "dormant", "global": "dormant"}
    matcher.send.assert_not_awaited()
    assert not client.exists("all_memory")


@pytest.mark.asyncio
async def test_sent_write_response_loss_keeps_ack_time_and_recovery_does_not_send(setup_runtime, monkeypatch):
    from src.services.chat.history_delivery import runtime
    client, services, incoming, transport, tools, matcher = setup_runtime
    ack_time = 1791240000123
    monkeypatch.setattr(runtime, "time", SimpleNamespace(time_ns=lambda: ack_time * 1000000))

    class LostSent(HistoryDeliveryStore):
        def transition(self, identity, token, operation, **kwargs):
            result = super().transition(identity, token, operation, **kwargs)
            if operation == "sent":
                raise EffectUnavailable("synthetic sent response loss")
            return result

    monkeypatch.setattr(runtime, "HistoryDeliveryStore", LostSent)
    await execution.execute(services, incoming, transport, tools, None)
    key, data = one_record(client)
    assert data["state"] == "sent" and data["delivered_at_ms"] == ack_time
    assert data["tasks"] == {"session": "complete", "global": "complete"}
    before = client.dump(key)
    await HistoryScanner(client).run_page()
    assert client.dump(key) == before and client.llen("all_memory") == 1
    matcher.send.assert_awaited_once()
    services.chat_engine.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_post_ack_exception_does_not_send_failure_notice_or_skip_history(setup_runtime):
    client, services, incoming, transport, tools, matcher = setup_runtime
    recorded = transport.reply_recorded

    async def post_ack_failure(text, **kwargs):
        assert await recorded(text, **kwargs) is True
        raise RuntimeError("synthetic post-ACK callback error")

    transport.reply_recorded = post_ack_failure
    await execution.execute(services, incoming, transport, tools, None)
    _, data = one_record(client)
    assert data["state"] == "sent" and data["tasks"] == {"session": "complete", "global": "complete"}
    transport.notice.assert_not_awaited()
    matcher.send.assert_awaited_once()
    assert client.llen("all_memory") == 1


@pytest.mark.asyncio
async def test_cancellation_after_observed_ack_preserves_sent_for_background_history(setup_runtime, monkeypatch):
    from src.services.chat.history_delivery import runtime

    client, services, incoming, transport, tools, matcher = setup_runtime
    ack_time = 1791240000123
    monkeypatch.setattr(runtime, "time", SimpleNamespace(time_ns=lambda: ack_time * 1000000))
    recorded = transport.reply_recorded

    async def cancelled_after_ack(text, **kwargs):
        assert await recorded(text, **kwargs) is True
        raise asyncio.CancelledError

    transport.reply_recorded = cancelled_after_ack
    with pytest.raises(asyncio.CancelledError):
        await execution.execute(services, incoming, transport, tools, None)
    key, data = one_record(client)
    assert data["state"] == "sent" and data["delivered_at_ms"] == ack_time
    assert data["tasks"] == {"session": "pending", "global": "pending"}
    assert client.pttl(key) == -1 and not client.exists("all_memory")
    assert json.loads(client.get("chat:history:group_8")) == [{"role": "user", "content": "old"}]
    await HistoryScanner(client).run_page()
    _, recovered = one_record(client)
    assert recovered["tasks"] == {"session": "complete", "global": "complete"}
    assert recovered["delivered_at_ms"] == ack_time and client.llen("all_memory") == 1
    matcher.send.assert_awaited_once()
    services.chat_engine.generate.assert_awaited_once()
    services.chat_engine.commit.assert_not_called()
    tools.cleanup_temp_files.assert_called_once()
    transport.notice.assert_not_awaited()
