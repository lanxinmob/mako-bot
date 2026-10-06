"""Event-controlled cancellation at the batch and session lock boundaries."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.services.chat.pipeline import workflow as module
from src.services.chat.pipeline.models import ChatInput
from src.services.chat.pipeline.workflow import ChatWorkflow
from src.services.chat.policy import ChatAddress
from src.utils.message import NormalizedMessage


class ObservedLock(asyncio.Lock):
    """Keep normal lock semantics and signal an actual blocked acquisition."""

    def __init__(self):
        super().__init__()
        self.blocked = asyncio.Event()

    async def acquire(self):
        if self.locked():
            self.blocked.set()
        return await super().acquire()


def setup(monkeypatch):
    entered = {name: asyncio.Event() for name in ("old", "new", "next")}
    gates = {name: asyncio.Event() for name in entered}

    async def debounce(delay):
        assert delay == 1
        name = asyncio.current_task().get_name()
        entered[name].set()
        await gates[name].wait()

    monkeypatch.setattr(module, "asyncio", SimpleNamespace(
        Lock=asyncio.Lock, sleep=debounce))
    workflow = ChatWorkflow(SimpleNamespace(
        settings=SimpleNamespace(chat_reply_debounce_seconds=1)))
    workflow.handle_locked = AsyncMock()
    return workflow, entered, gates


def incoming(text, started_at=0):
    return ChatInput(ChatAddress("group", 7, 1), "fixture", text,
                     NormalizedMessage(), True, False, started_at)


async def cancel_twice(task):
    task.cancel()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
@pytest.mark.parametrize("owner", ["latest", "old"])
async def test_cancel_while_waiting_for_second_guard(monkeypatch, owner):
    async def scenario():
        workflow, entered, gates = setup(monkeypatch)
        guard = ObservedLock()
        workflow._guard = guard
        key = (incoming("old").address.session_id, 7)
        tasks = []
        try:
            old = asyncio.create_task(workflow.handle(incoming("old"), "old"), name="old")
            tasks.append(old)
            await entered["old"].wait()
            if owner == "old":
                new = asyncio.create_task(
                    workflow.handle(incoming("new", 5), "new"), name="new")
                tasks.append(new)
                await entered["new"].wait()
                successor = workflow._pending[key]

            async with guard:
                gates["old"].set()
                await guard.blocked.wait()
                await cancel_twice(old)
                assert guard.locked()
                workflow.handle_locked.assert_not_awaited()
                if owner == "old":
                    assert workflow._pending[key] is successor
                else:
                    assert not workflow._pending

            if owner == "old":
                gates["new"].set()
                await new
                expected = ("old\nnew", 0, "new")
            else:
                fresh = asyncio.create_task(
                    workflow.handle(incoming("next", 10), "next"), name="next")
                tasks.append(fresh)
                await entered["next"].wait()
                gates["next"].set()
                await fresh
                expected = ("next", 10, "next")
            workflow.handle_locked.assert_awaited_once()
            request, transport = workflow.handle_locked.call_args.args
            assert (request.text, request.started_at, transport) == expected
            assert not workflow._pending
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    await asyncio.wait_for(scenario(), 5)


@pytest.mark.asyncio
async def test_cancel_dequeued_batch_waiting_for_session_lock_preserves_successor(monkeypatch):
    async def scenario():
        workflow, entered, gates = setup(monkeypatch)
        first = incoming("old")
        session = first.address.session_id
        lock = ObservedLock()
        workflow._locks[session] = lock
        tasks = []
        try:
            async with lock:
                old = asyncio.create_task(workflow.handle(first, "old"), name="old")
                tasks.append(old)
                await entered["old"].wait()
                gates["old"].set()
                await lock.blocked.wait()
                assert not workflow._pending

                new = asyncio.create_task(
                    workflow.handle(incoming("new", 5), "new"), name="new")
                tasks.append(new)
                await entered["new"].wait()
                successor = workflow._pending[(session, 7)]
                await cancel_twice(old)
                assert workflow._pending[(session, 7)] is successor
                assert lock.locked()
                workflow.handle_locked.assert_not_awaited()

            gates["new"].set()
            await new
            workflow.handle_locked.assert_awaited_once()
            request, transport = workflow.handle_locked.call_args.args
            assert (request.text, request.started_at, transport) == ("new", 5, "new")
            assert not workflow._pending
            assert not lock.locked()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    await asyncio.wait_for(scenario(), 5)
