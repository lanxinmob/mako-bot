"""Controlled history interleavings against actual packages and isolated Redis."""
import asyncio
from contextlib import suppress
from datetime import datetime
import json
import threading
from types import SimpleNamespace

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError, ResponseError

from src.models.schemas import ChatRecord
from src.services.chat.history_delivery.targets import HistoryTargets
from src.services.chat.history_delivery.worker import HistoryWorker
from src.services.persistence.effects import EffectNeedsReview, EffectWriter
from src.services.persistence.history_commit.delivery import HistoryDeliveryStore
from src.services.persistence.history_commit.plans import build_plan
from src.services.persistence.history_commit.snapshot import HistorySnapshots
from src.services.persistence.history_commit.task_scripts import TRANSITION
from src.services.persistence.history_commit.tasks import HistoryEffects
from test.autonomy.test_pending_atomic import isolated_redis


ACK_MS = 1791240000123
ACK_LOCAL = datetime(2026, 10, 6, 6, 40, 0, 123000)


@pytest.fixture
def history_case(isolated_redis):
    client = isolated_redis
    info = client.info("server")
    print(f"isolated history Redis pid={info['process_id']} "
          f"port={client.connection_pool.connection_kwargs['port']} "
          f"version={info['redis_version']}")
    snapshot = HistorySnapshots(client).read("group_8")
    plan = build_plan(
        "a" * 64, snapshot, bot_id="99", user_id=7, group_id=8,
        text="synthetic history interleaving",
        history=[{"role": "assistant", "content": "synthetic history interleaving"}],
        max_history_turns=2, global_max_records=1000, utc_offset_seconds=28800,
    )
    delivery = HistoryDeliveryStore(client)
    token = delivery.create(plan)
    assert token
    assert delivery.transition(plan.action_id, token, "begin") == "sending"
    assert delivery.transition(plan.action_id, token, "sent", delivered_at_ms=ACK_MS) == "sent"
    acknowledged = delivery.inspect(plan.action_id)
    assert acknowledged.confirmation_source == "transport"
    assert acknowledged.delivered_at_ms == ACK_MS
    key = delivery.key(plan.action_id)
    assert client.pttl(key) == -1
    return SimpleNamespace(client=client, plan=plan, delivery=delivery, key=key,
                           effects=HistoryEffects(client))


def task_for(case, kind):
    snapshot = case.effects.inspect(case.plan.action_id)
    return next(task for task in snapshot.tasks if task.kind == kind)


def make_due(case, kind, field):
    # Only isolated task deadlines change; avoid real lease sleeps/system clock changes.
    data = json.loads(case.client.get(case.key))
    seconds, micros = case.client.time()
    data["task_meta"][kind][field] = seconds * 1000 + micros // 1000 - 1
    case.client.set(case.key, json.dumps(data))


def global_receipt(case):
    return "mako:delivery:v1:effect:" + case.plan.effect_id("global")


def test_a1_valid_state_replacement_between_get_and_eval_rejects_claim(history_case):
    case = history_case
    changed = {}

    def replace_before_eval(*args):
        assert args[0] == TRANSITION and args[5] == "claim"
        assert args[3] == case.client.get(case.key)
        data = json.loads(args[3])
        assert data["state"] == "sent"
        data.update(state="unknown", delivered_at_ms=None,
                    tasks={"session": "dormant", "global": "dormant"})
        data.pop("task_meta", None)
        changed["raw"] = json.dumps(data)
        case.client.set(case.key, changed["raw"])
        # The replacement is independently valid, not merely corrupt JSON.
        assert case.delivery.inspect(case.plan.action_id).state == "unknown"
        return case.client.eval(*args)

    racing = HistoryEffects(SimpleNamespace(get=case.client.get, eval=replace_before_eval))
    assert racing.claim(case.plan.action_id, "global") is None
    assert case.client.get(case.key) == changed["raw"]
    assert case.client.pttl(case.key) == -1
    assert {task.state for task in case.effects.inspect(case.plan.action_id).tasks} == {"dormant"}
    assert case.client.get(global_receipt(case)) is None
    assert case.client.llen("all_memory") == 0


def test_a2_sibling_update_blocks_stale_finish_then_same_token_settles(history_case):
    case = history_case
    lease = case.effects.claim(case.plan.action_id, "session")
    outcome = HistoryTargets(case.client).apply(lease)
    assert outcome == "applied"
    history = case.client.get("chat:history:group_8")
    sibling = {}

    def claim_sibling_before_eval(*args):
        assert args[0] == TRANSITION and args[5] == "finish"
        sibling["lease"] = case.effects.claim(case.plan.action_id, "global")
        assert sibling["lease"] is not None
        sibling["raw"] = case.client.get(case.key)
        assert args[3] != sibling["raw"]
        return case.client.eval(*args)

    racing = HistoryEffects(SimpleNamespace(get=case.client.get, eval=claim_sibling_before_eval))
    assert not racing.finish(lease, outcome)
    assert case.client.get(case.key) == sibling["raw"]
    assert task_for(case, "session").state == "leased"
    assert task_for(case, "session").token == lease.task.token
    assert case.effects.finish(lease, outcome)
    session = task_for(case, "session")
    assert (session.state, session.result, session.token) == ("complete", "applied", lease.task.token)
    assert task_for(case, "global") == sibling["lease"].task
    settled = case.client.get(case.key)
    assert case.effects.finish(lease, outcome)
    assert case.client.get(case.key) == settled
    assert case.client.get("chat:history:group_8") == history


def test_a3_ttl_added_after_claim_refuses_settlement_without_mutation(history_case):
    case = history_case
    lease = case.effects.claim(case.plan.action_id, "global")
    case.client.pexpire(case.key, 60000)
    before = case.client.dump(case.key)
    with pytest.raises(EffectNeedsReview):
        case.effects.finish(lease, "applied")
    assert case.client.dump(case.key) == before
    assert 0 < case.client.pttl(case.key) <= 60000
    assert task_for(case, "global") == lease.task
    assert task_for(case, "session").state == "pending"
    assert case.client.get(global_receipt(case)) is None
    assert case.client.llen("all_memory") == 0


@pytest.mark.asyncio
async def test_b_cancelled_live_writer_arrives_after_new_holder_without_replay(history_case):
    case = history_case
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    actual = HistoryTargets(case.client)
    old, fresh = {}, {}

    def blocked_apply(lease):
        old["lease"] = lease
        entered.set()
        try:
            assert release.wait(5)
            old["outcome"] = actual.apply(lease)
            return old["outcome"]
        except Exception as exc:
            old["error"] = exc
            raise
        finally:
            finished.set()

    def fresh_apply(lease):
        fresh["lease"] = lease
        return actual.apply(lease)

    pending = asyncio.create_task(HistoryWorker(
        case.client, targets=SimpleNamespace(apply=blocked_apply),
    ).run_task(case.plan.action_id, "global"))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert task_for(case, "global") == old["lease"].task
        assert not finished.is_set() and not release.is_set()

        make_due(case, "global", "lease_until_ms")
        assert await HistoryWorker(case.client, targets=SimpleNamespace(
            apply=fresh_apply,
        )).run_task(case.plan.action_id, "global") == "applied"
        assert not finished.is_set()
        assert fresh["lease"].task.token != old["lease"].task.token
        assert fresh["lease"].task.attempts == old["lease"].task.attempts + 1
        assert fresh["lease"].plan == old["lease"].plan == case.plan
        assert fresh["lease"].delivered_at_ms == old["lease"].delivered_at_ms == ACK_MS
        settled = case.client.get(case.key)
        receipt = case.client.get(global_receipt(case))
        records = case.client.lrange("all_memory", 0, -1)
        assert len(records) == 1
        record = ChatRecord.model_validate_json(records[0])
        assert record.time == ACK_LOCAL and record.content == case.plan.data()["text"]
        assert (record.user_id, record.group_id) == (7, 8)

        release.set()
        assert await asyncio.to_thread(finished.wait, 5)
        assert "error" not in old and old["outcome"] == "already_applied"
        assert not case.effects.finish(old["lease"], "applied")
        assert not case.effects.defer(old["lease"])
        assert case.client.get(case.key) == settled
        assert case.client.get(global_receipt(case)) == receipt
        assert case.client.lrange("all_memory", 0, -1) == records
        current = task_for(case, "global")
        assert (current.state, current.result, current.token) == (
            "complete", "applied", fresh["lease"].task.token,
        )
        assert case.client.pttl(global_receipt(case)) == case.client.pttl(case.key) == -1
    finally:
        release.set()
        if not pending.done():
            pending.cancel()
            with suppress(asyncio.CancelledError):
                await pending
        if entered.is_set():
            assert await asyncio.to_thread(finished.wait, 5)


@pytest.mark.asyncio
async def test_c_partial_global_append_lost_error_keeps_started_and_session_independent(history_case):
    case = history_case
    actual = HistoryTargets(case.client)
    faults = []

    def append_then_lose_error(*args):
        assert args[1:4] == (2, global_receipt(case), "all_memory")
        marker = "redis.call('RPUSH', KEYS[2], p.record)"
        assert args[0].count(marker) == 1
        # Execute RPUSH in real Redis, then lose the actual server error reply.
        injected = args[0].replace(marker, marker + "\nif true then return "
                                   "redis.error_reply('synthetic partial append') end", 1)
        with pytest.raises(ResponseError, match="synthetic partial append"):
            case.client.eval(injected, *args[1:])
        faults.append(args[-3])
        raise RedisConnectionError("synthetic lost error response")

    actual.global_history = EffectWriter(SimpleNamespace(eval=append_then_lose_error))
    assert await HistoryWorker(case.client, targets=actual).run_task(
        case.plan.action_id, "global",
    ) == "unavailable"
    assert len(faults) == 1
    receipt = case.client.get(global_receipt(case))
    assert receipt == "started:" + faults[0]
    assert case.client.pttl(global_receipt(case)) == -1
    records = case.client.lrange("all_memory", 0, -1)
    assert len(records) == 1
    assert ChatRecord.model_validate_json(records[0]).time == ACK_LOCAL
    retry = task_for(case, "global")
    assert (retry.state, retry.result, retry.lease_until_ms) == ("retry_wait", "unavailable", 0)
    assert retry.next_attempt_at_ms > 0 and retry.attempts == 1
    sibling = task_for(case, "session")
    assert sibling.state == "pending" and sibling.attempts == 0

    make_due(case, "global", "next_attempt_at_ms")
    worker = HistoryWorker(case.client)
    assert await worker.run_task(case.plan.action_id, "global") == "target_incomplete"
    incomplete = task_for(case, "global")
    assert (incomplete.state, incomplete.result, incomplete.attempts) == (
        "needs_review", "target_incomplete", 2,
    )
    assert incomplete.token != retry.token
    assert incomplete.lease_until_ms == incomplete.next_attempt_at_ms == 0
    assert task_for(case, "session") == sibling
    assert case.client.get(global_receipt(case)) == receipt
    assert case.client.lrange("all_memory", 0, -1) == records

    assert await worker.run_task(case.plan.action_id, "session") == "applied"
    assert task_for(case, "session").state == "complete"
    assert json.loads(case.client.get("chat:history:group_8")) == case.plan.data()["history"]
    assert task_for(case, "global") == incomplete
    assert await worker.run_task(case.plan.action_id, "global") == "not_claimed"
    assert await worker.run_action(case.plan.action_id) == ()
    assert case.client.get(global_receipt(case)) == receipt
    assert case.client.pttl(global_receipt(case)) == case.client.pttl(case.key) == -1
    assert case.client.lrange("all_memory", 0, -1) == records
