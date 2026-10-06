"""Bounded SCAN continuation; receipts and send eligibility are not task inputs."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.services.delivery.effects.discovery import EffectScanner
from src.services.delivery.effects.worker import EffectWorker
from src.services.delivery.state import DeliveryStore
from src.services.persistence.effects import EffectNeedsReview, EffectUnavailable
from test.autonomy.test_pending_atomic import isolated_redis
from test.delivery.effects.test_effect_leases import activate


@pytest.mark.asyncio
async def test_oversized_scan_batch_keeps_remaining_keys_and_global_task_budget():
    ids = [f"{number:064x}" for number in range(1, 6)]
    keys = ["mako:delivery:v1:" + action_id for action_id in ids]
    client = SimpleNamespace(scan=Mock(return_value=(0, list(reversed(keys)))))

    async def run(action_id, *, limit):
        return ((action_id, "applied"),)

    worker = SimpleNamespace(run_action=AsyncMock(side_effect=run))
    scanner = EffectScanner(client, worker=worker)
    first = await scanner.run_page(key_limit=10, task_limit=3)
    assert first.next_cursor == "0:3" and first.visited == 3
    second = await scanner.run_page(first.next_cursor)
    assert second.next_cursor is None and second.visited == 2
    assert [call.args[0] for call in worker.run_action.await_args_list] == ids
    assert [call.kwargs["limit"] for call in worker.run_action.await_args_list] == [3, 2, 1, 3, 2]


@pytest.mark.asyncio
async def test_metadata_keys_and_empty_nonterminal_pages_do_not_authorize_work():
    client = SimpleNamespace(scan=Mock(side_effect=[
        (7, []), (0, [b"mako:delivery:v1:source:reminder", b"mako:delivery:v1:effect:" + b"a" * 64])]))
    worker = SimpleNamespace(run_action=AsyncMock())
    scanner = EffectScanner(client, worker=worker)
    first = await scanner.run_page()
    assert first.next_cursor == "7:0" and first.visited == 0
    second = await scanner.run_page(first.next_cursor)
    assert second.next_cursor is None and second.visited == 2
    worker.run_action.assert_not_awaited()


@pytest.mark.asyncio
async def test_bad_record_does_not_block_next_action():
    keys = ["mako:delivery:v1:" + digit * 64 for digit in ("a", "b")]
    client = SimpleNamespace(scan=Mock(return_value=(0, keys)))
    worker = SimpleNamespace(run_action=AsyncMock(side_effect=[EffectNeedsReview(), (("effect", "applied"),)]))
    page = await EffectScanner(client, worker=worker).run_page()
    assert page.outcomes == (("a" * 64, "needs_review"), ("effect", "applied"))
    assert page.next_cursor is None


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["scan", "read"])
async def test_storage_outage_propagates_instead_of_faking_finished_page(phase):
    client = SimpleNamespace(scan=Mock(return_value=(0, ["mako:delivery:v1:" + "a" * 64])))
    worker = SimpleNamespace(run_action=AsyncMock(side_effect=EffectUnavailable))
    if phase == "scan":
        client.scan.side_effect = ConnectionError("synthetic offline")
    with pytest.raises(EffectUnavailable):
        await EffectScanner(client, worker=worker).run_page("13:0")


@pytest.mark.asyncio
async def test_partial_action_budget_finishes_on_next_pass_without_bot(isolated_redis):
    client = isolated_redis
    spec, store = activate(client)
    keys = [DeliveryStore.key(spec.action_id)]
    # Deterministic discovery over a real stored plan and actual consumer.
    discovery = SimpleNamespace(scan=Mock(return_value=(0, keys)))
    scanner = EffectScanner(discovery, worker=EffectWorker(client))
    first = await scanner.run_page(task_limit=2)
    assert len(first.outcomes) == 2 and first.next_cursor is None
    assert [task.state for task in store.inspect(spec.action_id).tasks] == ["complete", "complete", "pending"]
    second = await scanner.run_page()
    assert len(second.outcomes) == 1
    assert all(task.state == "complete" for task in store.inspect(spec.action_id).tasks)
    assert client.llen("all_memory") == 1
