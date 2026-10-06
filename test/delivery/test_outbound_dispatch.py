from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from src.services.delivery.dispatcher import OutboundDispatcher


@pytest.mark.asyncio
async def test_invalidation_before_send_task_starts_does_not_send_or_charge():
    dispatcher = OutboundDispatcher(spacing=0, max_per_window=1, required_wait=0)
    valid = True
    sent = []

    def invalidate():
        nonlocal valid
        valid = False

    async def send():
        sent.append("reply")

    # A queued inbound callback runs when the timeout wrapper yields to its
    # send task. The final guard must see that callback's updated state.
    asyncio.get_running_loop().call_soon(invalidate)
    assert not await dispatcher.dispatch(
        "group", 1, send, guard=lambda: valid, notice_key="candidate"
    )
    assert not sent
    state = dispatcher._targets[("group", "1")]
    assert not state.attempts and not state.notices
    assert await dispatcher.dispatch("group", 1, send, category="command")
    assert sent == ["reply"]


@pytest.mark.asyncio
async def test_shared_spacing_and_guard_rechecked_after_wait() -> None:
    dispatcher = OutboundDispatcher(spacing=0.03, window=1, chat_wait=0.2)
    sent = []
    valid = True

    async def send():
        sent.append(time.monotonic())

    assert await dispatcher.dispatch("group", 1, send, category="command")
    candidate = asyncio.create_task(dispatcher.dispatch("group", 1, send, guard=lambda: valid))
    await asyncio.sleep(0)
    valid = False
    assert not await candidate
    assert len(sent) == 1
    assert await dispatcher.dispatch("group", 1, send, category="reminder")
    assert sent[1] - sent[0] >= 0.025


@pytest.mark.asyncio
async def test_guard_and_send_have_separate_timeout_budgets():
    dispatcher = OutboundDispatcher(spacing=0, send_timeout=0.1)
    calls = []

    async def guard():
        calls.append("claim")
        await asyncio.sleep(0.06)
        return True

    async def send():
        calls.append("send")
        await asyncio.sleep(0.06)

    assert await dispatcher.dispatch("group", 1, send, guard=guard)
    assert calls == ["claim", "send"]


@pytest.mark.asyncio
async def test_timed_out_guard_cannot_send_when_it_swallows_cancellation():
    dispatcher = OutboundDispatcher(spacing=0, send_timeout=0.01)
    sent = []

    async def guard():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return True

    async def send():
        sent.append(True)

    assert not await dispatcher.dispatch("group", 1, send, guard=guard, notice_key="guard")
    state = dispatcher._targets[("group", "1")]
    assert not sent and not state.attempts and not state.notices
    assert not state.busy and not state.pending


@pytest.mark.asyncio
async def test_repeated_cancellation_does_not_release_slot_before_child_cleanup():
    dispatcher = OutboundDispatcher(spacing=0)
    entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def send():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release.wait()

    task = asyncio.create_task(dispatcher.dispatch("group", 1, send))
    await entered.wait()
    task.cancel()
    await cleaning.wait()
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    assert dispatcher._targets[("group", "1")].busy
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not dispatcher._targets[("group", "1")].busy


@pytest.mark.asyncio
async def test_priority_cancellation_and_per_target_serialization() -> None:
    dispatcher = OutboundDispatcher(spacing=0, window=1)
    entered, release = asyncio.Event(), asyncio.Event()
    sent = []

    async def first():
        entered.set()
        await release.wait()
        sent.append("first")

    async def send(label):
        sent.append(label)

    active = asyncio.create_task(dispatcher.dispatch("group", 1, first, category="command"))
    await entered.wait()
    chat = asyncio.create_task(dispatcher.dispatch("group", 1, lambda: send("chat")))
    cancelled = asyncio.create_task(dispatcher.dispatch("group", 1, lambda: send("cancelled")))
    command = asyncio.create_task(dispatcher.dispatch("group", 1, lambda: send("command"), category="command"))
    reminder = asyncio.create_task(dispatcher.dispatch("group", 1, lambda: send("reminder"), category="reminder"))
    await asyncio.sleep(0)
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    # A blocked group does not hold up another group or the same ID in private.
    assert await dispatcher.dispatch("private", 1, lambda: send("private"), category="command")
    release.set()
    assert all(await asyncio.gather(active, chat, command, reminder))
    assert sent == ["private", "first", "reminder", "command", "chat"]
    assert not dispatcher._targets[("group", "1")].pending


@pytest.mark.asyncio
async def test_category_limits_share_global_attempt_budget() -> None:
    dispatcher = OutboundDispatcher(spacing=0, window=10, chat_wait=0,
                                    required_wait=0, max_per_window=6)
    async def send():
        return {"message_id": 1}

    for _ in range(3):
        assert await dispatcher.dispatch("group", 1, send)
    assert not await dispatcher.dispatch("group", 1, send)
    assert await dispatcher.dispatch("group", 1, send, category="news")
    assert not await dispatcher.dispatch("group", 1, send, category="autonomous")
    assert await dispatcher.dispatch("group", 1, send, category="command")
    assert await dispatcher.dispatch("group", 1, send, category="reminder")
    assert not await dispatcher.dispatch("group", 1, send, category="command")


@pytest.mark.asyncio
async def test_queue_and_target_bounds_do_not_acknowledge_delivery() -> None:
    dispatcher = OutboundDispatcher(spacing=0, max_pending=1, max_targets=1)
    entered, release = asyncio.Event(), asyncio.Event()
    async def send():
        entered.set()
        await release.wait()

    task = asyncio.create_task(dispatcher.dispatch("group", 1, send, category="command"))
    await entered.wait()
    assert not await dispatcher.dispatch("group", 1, send, category="reminder")
    assert not await dispatcher.dispatch("group", 2, send, category="command")
    assert len(dispatcher._targets) == 1
    release.set()
    assert await task


@pytest.mark.asyncio
async def test_failed_attempts_consume_quota_and_notices_coalesce(caplog) -> None:
    dispatcher = OutboundDispatcher(spacing=0, max_per_window=3, required_wait=0)
    calls = 0
    async def fail():
        nonlocal calls
        calls += 1
        raise OSError("offline")

    assert not await dispatcher.dispatch("group", 1, fail, category="command", notice_key="offline")
    assert not await dispatcher.dispatch("group", 1, fail, category="command", notice_key="offline")
    assert calls == 1
    assert not await dispatcher.dispatch("group", 1, fail, category="command")
    assert not await dispatcher.dispatch("group", 1, fail, category="command")
    assert not await dispatcher.dispatch("group", 1, fail, category="command")
    assert calls == 3
    assert sum("Outbound failed" in item.message for item in caplog.records) == 1


@pytest.mark.asyncio
async def test_guard_timeout_does_not_consume_send_budget() -> None:
    dispatcher = OutboundDispatcher(spacing=0, send_timeout=0.01)
    sent = []
    async def guard():
        await asyncio.Event().wait()
    async def send():
        sent.append(True)
    assert not await dispatcher.dispatch("group", 1, send, guard=guard)
    assert not sent
    assert not dispatcher._targets[("group", "1")].attempts
    assert await dispatcher.dispatch("group", 1, send, category="command")




@pytest.mark.asyncio
async def test_command_failure_notice_is_sent_once_and_result_stays_false(monkeypatch) -> None:
    from src.services.delivery import dispatcher as module
    dispatcher = OutboundDispatcher(spacing=0)
    monkeypatch.setattr(module, "dispatch", dispatcher.dispatch)
    messages = []
    class Matcher:
        async def send(self, message):
            if message == "result":
                raise OSError("offline for original result")
            messages.append(message)
    event = SimpleNamespace(group_id=1, user_id=2)
    assert not await module.send_to_event(Matcher(), event, "result")
    assert not await module.send_to_event(Matcher(), event, "result")
    assert len(messages) == 1
    assert "送达状态未确认" in messages[0]


def test_configure_keeps_live_dispatcher_state(monkeypatch) -> None:
    from src.services.delivery import dispatcher as module
    dispatcher = OutboundDispatcher()
    monkeypatch.setattr(module, "outbound", dispatcher)
    monkeypatch.setattr(module, "_configured", False)
    module.configure_outbound(SimpleNamespace(outbound_max_per_minute=12, outbound_chat_max_per_minute=4,
                                             outbound_unsolicited_max_per_minute=2, outbound_max_targets=50))
    assert module.outbound is dispatcher
    assert (dispatcher.max_per_window, dispatcher.chat_max_per_window,
            dispatcher.unsolicited_max_per_window, dispatcher.max_targets) == (12, 4, 2, 50)


@pytest.mark.asyncio
@pytest.mark.parametrize("wait", [0, 0.02])
async def test_wait_budget_expires_while_another_send_is_active(wait):
    dispatcher = OutboundDispatcher(spacing=0, required_wait=wait, send_timeout=2)
    entered, release = asyncio.Event(), asyncio.Event()
    sent = []

    async def first():
        entered.set()
        await release.wait()

    async def second():
        sent.append(True)

    active = asyncio.create_task(dispatcher.dispatch("group", 1, first, category="command"))
    await entered.wait()
    try:
        assert not await asyncio.wait_for(
            dispatcher.dispatch("group", 1, second, category="reminder"), 0.3
        )
        assert not active.done() and not sent
        assert len(dispatcher._targets[("group", "1")].pending) == 1
    finally:
        release.set()
        await active
    assert await dispatcher.dispatch("group", 1, second, category="command")


@pytest.mark.asyncio
async def test_cancel_active_send_releases_slot_to_waiter():
    dispatcher = OutboundDispatcher(spacing=0, required_wait=1)
    entered = asyncio.Event()

    async def blocked():
        entered.set()
        await asyncio.Event().wait()

    async def next_send():
        return True

    active = asyncio.create_task(dispatcher.dispatch("group", 1, blocked, category="command"))
    await entered.wait()
    waiting = asyncio.create_task(dispatcher.dispatch("group", 1, next_send, category="reminder"))
    await asyncio.sleep(0)
    active.cancel()
    with pytest.raises(asyncio.CancelledError):
        await active
    assert await asyncio.wait_for(waiting, 0.3)
    state = dispatcher._targets[("group", "1")]
    assert not state.pending and not state.busy
