import asyncio
from datetime import datetime
import json
import threading
from types import SimpleNamespace

import pytest

from src.models.schemas import ChatRecord
from src.services.chat.history_delivery.targets import HistoryTargets
from src.services.chat.history_delivery.worker import HistoryWorker
from src.services.persistence.effects import EffectUnavailable
from test.autonomy.test_pending_atomic import isolated_redis
from test.persistence.history_commit.test_delivery import planned
from test.persistence.history_commit.test_tasks import acknowledged, make_due


@pytest.mark.asyncio
async def test_session_conflict_preserves_new_history_and_global_keeps_ack_time(acknowledged):
    client, delivery, plan, store = acknowledged
    newer = '[{"role":"user","content":"newer"}]'
    client.set("chat:history:group_8", newer)
    worker = HistoryWorker(client)
    outcomes = dict(await worker.run_action(plan.action_id))
    assert outcomes == {"session": "history_conflict", "global": "applied"}
    assert client.get("chat:history:group_8") == newer
    record = ChatRecord.model_validate_json(client.lindex("all_memory", 0))
    assert record.time == datetime(2026, 10, 6, 6, 40, 0, 123000)
    assert record.content == plan.data()["text"] and record.group_id == 8 and record.user_id == 7
    assert await worker.run_action(plan.action_id) == ()
    assert client.llen("all_memory") == 1


@pytest.mark.asyncio
async def test_target_and_settlement_response_losses_recover_without_duplicate(acknowledged):
    client, delivery, plan, store = acknowledged
    actual = HistoryTargets(client)

    def lost_target(lease):
        actual.apply(lease)
        raise EffectUnavailable("synthetic target response loss")

    worker = HistoryWorker(client, targets=SimpleNamespace(apply=lost_target))
    assert await worker.run_task(plan.action_id, "session") == "unavailable"
    assert json.loads(client.get("chat:history:group_8")) == plan.data()["history"]
    make_due(client, delivery, plan, "session", "next_attempt_at_ms")
    assert await HistoryWorker(client).run_task(plan.action_id, "session") == "already_applied"

    assert await worker.run_task(plan.action_id, "global") == "unavailable"
    assert client.llen("all_memory") == 1
    make_due(client, delivery, plan, "global", "next_attempt_at_ms")
    original_finish = store.finish

    def lost_finish(*args):
        assert original_finish(*args)
        raise EffectUnavailable("synthetic settlement response loss")

    store.finish = lost_finish
    assert await HistoryWorker(client, store=store).run_task(plan.action_id, "global") == "settlement_unconfirmed"
    assert await HistoryWorker(client).run_task(plan.action_id, "global") == "not_claimed"
    assert client.llen("all_memory") == 1


@pytest.mark.asyncio
async def test_cancelled_writer_retains_lease_and_receipt_for_later_recovery(acknowledged):
    client, delivery, plan, store = acknowledged
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    actual = HistoryTargets(client)

    def slow(lease):
        entered.set()
        assert release.wait(5)
        try:
            return actual.apply(lease)
        finally:
            finished.set()

    task = asyncio.create_task(HistoryWorker(client, targets=SimpleNamespace(apply=slow)).run_task(plan.action_id, "global"))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert store.claim(plan.action_id, "global") is None
        current = next(t for t in store.inspect(plan.action_id).tasks if t.kind == "global")
        assert current.state == "leased" and current.result == ""
    finally:
        release.set()
        assert await asyncio.to_thread(finished.wait, 5)
    make_due(client, delivery, plan, "global", "lease_until_ms")
    assert await HistoryWorker(client).run_task(plan.action_id, "global") == "already_applied"
    assert client.llen("all_memory") == 1
