"""Controlled scheduling with actual Redis state transitions and no QQ network."""
import asyncio

import pytest

from src.services.autonomy import execution
from src.services.autonomy.approval import ApprovalUnavailable
from src.services.delivery.dispatcher import OutboundDispatcher
from test.autonomy.test_pending_atomic import isolated_redis
from test.autonomy.test_approval import approval
from test.autonomy.test_execution import scene


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_task", [False, True])
async def test_queued_cancel_never_sends(scene, approval, monkeypatch, cancel_task):
    ctx, bot = scene
    _, store, snapshot = approval
    dispatcher = OutboundDispatcher(spacing=0)
    occupied, release, queued = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def blocker():
        occupied.set()
        await release.wait()

    async def dispatch(*args, **kwargs):
        queued.set()
        return await dispatcher.dispatch(*args, **kwargs)

    monkeypatch.setattr(execution, "dispatch", dispatch)
    blocker_task = asyncio.create_task(dispatcher.dispatch("group", 7, blocker, category="command"))
    task = None
    try:
        await asyncio.wait_for(occupied.wait(), 2)
        task = asyncio.create_task(execution.send_approved(ctx, bot, store, snapshot))
        await asyncio.wait_for(queued.wait(), 2)
        if cancel_task:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert store.inspect("p1").state == "rejected_before_send"
        else:
            assert store.cancel(snapshot).ok
            release.set()
            assert "未进入发送" in await asyncio.wait_for(task, 2)
            assert store.inspect("p1").state == "cancelled"
        bot.send_group_msg.assert_not_awaited()
    finally:
        release.set()
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await blocker_task


@pytest.mark.asyncio
async def test_cancel_during_transport_retains_unknown(scene, approval):
    ctx, bot = scene
    _, store, snapshot = approval
    entered = asyncio.Event()

    async def transport(**kwargs):
        entered.set()
        await asyncio.Event().wait()

    bot.send_group_msg.side_effect = transport
    task = asyncio.create_task(execution.send_approved(ctx, bot, store, snapshot))
    try:
        await asyncio.wait_for(entered.wait(), 2)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert store.inspect("p1").state == "unknown"
    assert not store.claim(snapshot, "original").ok
    bot.send_group_msg.assert_awaited_once()


@pytest.mark.asyncio
async def test_begin_response_loss_does_not_send_or_release(scene, approval, monkeypatch):
    ctx, bot = scene
    _, store, snapshot = approval
    begin = store.begin_send

    def response_lost(*args):
        assert begin(*args).ok
        raise ApprovalUnavailable("synthetic response loss after Redis write")

    monkeypatch.setattr(store, "begin_send", response_lost)
    assert "状态未确认" in await execution.send_approved(ctx, bot, store, snapshot)
    assert store.inspect("p1").state == "unknown"
    assert not store.claim(snapshot, "original").ok
    bot.send_group_msg.assert_not_awaited()
