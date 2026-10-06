import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from src.services.chat.history_delivery.discovery import HistoryScanner
from src.services.chat.history_delivery.targets import HistoryTargets
from src.services.chat.history_delivery.worker import HistoryWorker
from src.services.persistence.effects import EffectUnavailable
from src.services.persistence.history_commit.plans import HistoryDeliveryPlan, canonical
from src.services.persistence.history_commit.task_scripts import TRANSITION
from src.services.persistence.history_commit.tasks import HistoryEffects
from test.autonomy.test_pending_atomic import isolated_redis
from test.persistence.history_commit.test_delivery import planned
from test.persistence.history_commit.test_tasks import acknowledged
from test.delivery.test_sender_acknowledgement import load_function


class PageClient:
    """Control SCAN only; state, leases and targets use the fixture's real Redis."""

    def __init__(self, client, keys, *, failed_operation=None, after_write=False):
        self.client, self.keys = client, keys
        self.failed_operation, self.after_write = failed_operation, after_write
        self.failed_calls = 0

    def get(self, key):
        return self.client.get(key)

    def execute_command(self, *args, **kwargs):
        assert args[0] == "SCAN" and args[1] == 17
        assert kwargs == {"NEVER_DECODE": True}
        return 23, self.keys

    def eval(self, *args):
        if args[0] == TRANSITION and args[4] == "session" and args[5] == self.failed_operation:
            self.failed_calls += 1
            if self.after_write:
                self.client.eval(*args)
            raise RedisConnectionError("synthetic lease operation response unavailable")
        return self.client.eval(*args)


class UnavailableSessionTarget:
    def __init__(self, client):
        self.actual = HistoryTargets(client)

    def apply(self, lease):
        if lease.task.kind == "session":
            raise EffectUnavailable("synthetic target unavailable")
        return self.actual.apply(lease)


def recovery_tick(client, scanner):
    namespace = {
        "asyncio": asyncio, "_storage": SimpleNamespace(redis=client), "get_settings": Mock(),
        "logger": Mock(), "_cursor": "1:0", "_effects_cursor": "2:0",
        "_generation_cursor": "3:0", "_history_cursor": "17:0", "_reminder_cursor": "4:0",
        "_reminder_intents": False,
        "reminder_runtime": AsyncMock(return_value=SimpleNamespace(
            restore_page=AsyncMock(return_value=("5:0", 0)))),
        "_runner": Mock(return_value=SimpleNamespace(run_page=AsyncMock(return_value=("6:0", ())))),
        "EffectScanner": Mock(return_value=SimpleNamespace(
            run_page=AsyncMock(return_value=SimpleNamespace(next_cursor="7:0")))),
        "GenerationCostScanner": Mock(return_value=SimpleNamespace(
            run_due=AsyncMock(), repair_page=AsyncMock(return_value=SimpleNamespace(next_cursor="8:0")))),
        "HistoryScanner": lambda _: scanner,
    }
    tick = load_function("src/plugins/chat/recovery.py", "recover_background_deliveries", namespace)
    return tick, namespace


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["claim", "finish", "defer"])
@pytest.mark.parametrize("after_write", [False, True])
async def test_actual_worker_outage_keeps_recovery_cursor_after_sibling_attempt(acknowledged, operation, after_write):
    client, delivery, plan, store = acknowledged
    key = delivery.key(plan.action_id)
    proxy = PageClient(client, [key.encode()], failed_operation=operation, after_write=after_write)
    targets = UnavailableSessionTarget(client) if operation == "defer" else HistoryTargets(client)
    scanner = HistoryScanner(proxy, worker=HistoryWorker(proxy, targets=targets))
    tick, namespace = recovery_tick(proxy, scanner)
    await tick()
    assert namespace["_history_cursor"] == "17:0"
    assert proxy.failed_calls == 1 and namespace["logger"].warning.call_count == 1
    assert (namespace["_cursor"], namespace["_effects_cursor"], namespace["_generation_cursor"],
            namespace["_reminder_cursor"]) == ("6:0", "7:0", "8:0", "5:0")
    snapshot = HistoryEffects(client).inspect(plan.action_id)
    tasks = {task.kind: task for task in snapshot.tasks}
    assert tasks["global"].state == "complete" and client.llen("all_memory") == 1
    expected = ({"claim": "leased", "finish": "complete", "defer": "retry_wait"}[operation]
                if after_write else "pending" if operation == "claim" else "leased")
    assert tasks["session"].state == expected
    assert snapshot.delivery.delivered_at_ms == 1791240000123 and client.pttl(key) == -1
    assert client.pttl("mako:delivery:v1:effect:" + plan.effect_id("global")) == -1


@pytest.mark.asyncio
async def test_bad_lease_evidence_advances_to_good_record_without_stalling_page(acknowledged):
    client, delivery, plan, store = acknowledged
    bad_key = delivery.key(plan.action_id)
    client.pexpire(bad_key, 60000)
    bad_before = client.dump(bad_key)
    data = plan.data()
    data["action_id"] = "b" * 64
    good = HistoryDeliveryPlan(canonical(data))
    token = delivery.create(good)
    assert delivery.transition(good.action_id, token, "begin") == "sending"
    assert delivery.transition(good.action_id, token, "sent", delivered_at_ms=1791240000123) == "sent"
    good_key = delivery.key(good.action_id)
    proxy = PageClient(client, [bad_key.encode(), good_key.encode()])
    scanner = HistoryScanner(proxy)
    first = await scanner.run_page("17:0")
    assert first.outcomes == (("session", "needs_review"), ("global", "needs_review"))
    assert first.next_cursor == "17:1" and client.dump(bad_key) == bad_before
    second = await scanner.run_page(first.next_cursor)
    assert second.next_cursor == "23:0" and client.llen("all_memory") == 1
    assert all(task.state == "complete" for task in HistoryEffects(client).inspect(good.action_id).tasks)
    assert client.dump(bad_key) == bad_before and client.pttl(bad_key) > 0


@pytest.mark.asyncio
async def test_target_failure_with_confirmed_defer_allows_scanning_to_continue(acknowledged):
    client, delivery, plan, store = acknowledged
    proxy = PageClient(client, [delivery.key(plan.action_id).encode()])
    worker = HistoryWorker(proxy, targets=UnavailableSessionTarget(client))
    page = await HistoryScanner(proxy, worker=worker).run_page("17:0")
    assert page.next_cursor == "23:0" and page.outcomes == (("session", "unavailable"), ("global", "applied"))
    tasks = {task.kind: task for task in HistoryEffects(client).inspect(plan.action_id).tasks}
    assert tasks["session"].state == "retry_wait" and tasks["global"].state == "complete"
