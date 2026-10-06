from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.services.chat.generation.discovery import GenerationCostScanner
from src.services.persistence.effects import EffectNeedsReview, EffectUnavailable
from test.autonomy.test_pending_atomic import isolated_redis
from test.chat.generation.test_store import attempt


@pytest.mark.asyncio
async def test_bounded_discovery_keeps_overflow_and_isolates_invalid_records():
    ids = [f"{index:064x}" for index in range(5)]
    keys = ["mako:generation:v1:" + value for value in ids]
    client = SimpleNamespace(execute_command=Mock(return_value=(0, list(reversed(keys)))))
    worker = SimpleNamespace(run=AsyncMock(side_effect=[
        "not_claimed", EffectNeedsReview(), "applied", "not_claimed", "applied"]))
    scanner = GenerationCostScanner(client, worker=worker)
    first = await scanner.run_page()
    assert first.next_cursor == "0:3" and first.visited == 3
    assert first.outcomes[1] == (ids[1], "needs_review")
    last = await scanner.run_page(first.next_cursor)
    assert last.next_cursor is None and last.visited == 2
    assert [call.args[0] for call in worker.run.await_args_list] == ids


@pytest.mark.asyncio
async def test_empty_page_continues_and_outage_does_not_finish_cursor():
    key = "mako:generation:v1:" + "a" * 64
    client = SimpleNamespace(execute_command=Mock(side_effect=[(8, []), (0, [key])]))
    worker = SimpleNamespace(run=AsyncMock(side_effect=EffectUnavailable))
    scanner = GenerationCostScanner(client, worker=worker)
    page = await scanner.run_page()
    assert page.next_cursor == "8:0" and page.visited == 0
    with pytest.raises(EffectUnavailable):
        await scanner.run_page(page.next_cursor)


@pytest.mark.asyncio
async def test_due_consumer_bypasses_history_and_clears_bad_head(attempt, monkeypatch):
    from src.services.persistence.generation.index_scripts import COST_DUE_KEY
    from src.services.persistence.generation.costs import GenerationCosts
    client, store, spec = attempt
    store.complete(spec, store.start(spec), .02)
    client.zadd(COST_DUE_KEY, {b"\xff": 0, "broken-id": 0})
    execute = client.execute_command

    def without_scan(command, *args, **kwargs):
        assert command.upper() != "SCAN", "due path must not scan history"
        return execute(command, *args, **kwargs)

    monkeypatch.setattr(client, "execute_command", without_scan)
    page = await GenerationCostScanner(client).run_due()
    assert page.visited == 3
    assert [outcome for _, outcome in page.outcomes] == ["removed_missing", "removed_missing", "applied"]
    assert GenerationCosts(client).inspect(spec.attempt_id).state == "complete"
    assert client.zcard(COST_DUE_KEY) == 0


@pytest.mark.asyncio
async def test_due_consumer_keeps_unknown_unbilled(attempt):
    from src.services.persistence.generation.index_scripts import COST_DUE_KEY
    client, store, spec = attempt
    store.mark_unknown(spec, store.start(spec))
    before = client.get(store.key(spec.attempt_id))
    client.zadd(COST_DUE_KEY, {spec.attempt_id: 0})
    before_keys = set(client.scan_iter())
    page = await GenerationCostScanner(client).run_due()
    assert client.get(store.key(spec.attempt_id)) == before
    assert client.zcard(COST_DUE_KEY) == 0
    assert page.outcomes == ((spec.attempt_id, "not_claimed"),)
    assert set(client.scan_iter()) == before_keys - {COST_DUE_KEY}


@pytest.mark.asyncio
async def test_repair_rebuilds_lost_index_without_charging(attempt):
    from src.services.persistence.generation.index_scripts import COST_DUE_KEY
    from src.services.persistence.generation.costs import GenerationCosts
    client, store, spec = attempt
    store.complete(spec, store.start(spec), .02)
    client.delete(COST_DUE_KEY)
    malformed_key = b"mako:generation:v1:\xff"
    client.set(malformed_key, b"preserve evidence")
    worker = SimpleNamespace(run=AsyncMock(side_effect=AssertionError("repair cannot charge")))
    scanner = GenerationCostScanner(client, worker=worker)
    cursor = "0:0"
    for _ in range(20):
        page = await scanner.repair_page(cursor)
        if page.next_cursor is None:
            break
        cursor = page.next_cursor
    else:
        pytest.fail("small isolated fixture did not finish scan")
    assert scanner.index.due_ids() == [spec.attempt_id]
    assert GenerationCosts(client).inspect(spec.attempt_id).state == "pending"
    assert client.get(malformed_key) == "preserve evidence"
    worker.run.assert_not_awaited()


@pytest.mark.asyncio
async def test_repair_budget_retains_overflow_without_consuming():
    ids = [f"{number:064x}" for number in range(12)]
    client = SimpleNamespace(execute_command=Mock(return_value=(0, ["mako:generation:v1:" + id for id in ids])))
    index = SimpleNamespace(repair_current=Mock(return_value="repaired"))
    worker = SimpleNamespace(run=AsyncMock())
    scanner = GenerationCostScanner(client, worker=worker, index=index)
    first = await scanner.repair_page()
    assert first.visited == 10 and first.next_cursor == "0:10"
    last = await scanner.repair_page(first.next_cursor)
    assert last.visited == 2 and last.next_cursor is None
    assert [call.args[0] for call in index.repair_current.call_args_list] == ids
    worker.run.assert_not_awaited()
