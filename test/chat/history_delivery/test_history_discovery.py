from types import SimpleNamespace

import pytest

from src.services.chat.history_delivery.discovery import HistoryScanner
from src.services.persistence.effects import EffectNeedsReview, EffectUnavailable


class ScanClient:
    def __init__(self, following, keys):
        self.following, self.keys, self.calls = following, keys, []

    def execute_command(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.following, self.keys


@pytest.mark.asyncio
async def test_oversized_scan_keeps_offset_and_limits_task_attempts():
    keys = [f"mako:chat:delivery:v1:{number:064x}".encode() for number in range(14)]
    client = ScanClient(7, keys)
    calls = []

    async def run(identity, *, limit, raise_on_unavailable):
        assert raise_on_unavailable is True
        calls.append((identity, limit))
        return (("global", "applied"),)

    scanner = HistoryScanner(client, worker=SimpleNamespace(run_action=run), classifier=lambda _: "unchanged")
    first = await scanner.run_page()
    assert first.visited == 2 and first.next_cursor == "0:2" and len(calls) == 2
    assert [limit for _, limit in calls] == [2, 1]
    tail = await scanner.run_page("0:12")
    assert tail.visited == 2 and tail.next_cursor == "7:0"
    assert calls[-1][0] == f"{13:064x}"
    assert client.calls[0] == (("SCAN", 0, "MATCH", "mako:chat:delivery:v1:*", "COUNT", 10), {"NEVER_DECODE": True})


@pytest.mark.asyncio
async def test_invalid_names_review_records_and_empty_nonterminal_page():
    client = ScanClient(0, [b"mako:chat:delivery:v1:\xff", b"mako:chat:delivery:v1:effect:receipt",
                            ("mako:chat:delivery:v1:" + "a" * 64).encode(),
                            ("mako:chat:delivery:v1:" + "b" * 64).encode()])
    calls = []

    async def run(identity, *, limit, raise_on_unavailable):
        assert raise_on_unavailable is True
        calls.append(identity)
        if identity == "a" * 64:
            raise EffectNeedsReview("synthetic corruption")
        return ()

    page = await HistoryScanner(client, worker=SimpleNamespace(run_action=run), classifier=lambda _: "unchanged").run_page()
    assert page.visited == 4 and page.next_cursor is None
    assert page.outcomes == (("a" * 64, "needs_review"),)
    assert calls == ["a" * 64, "b" * 64]
    empty = await HistoryScanner(ScanClient(9, [])).run_page()
    assert empty.visited == 0 and empty.next_cursor == "9:0"


@pytest.mark.asyncio
async def test_read_outage_does_not_report_false_finished_page():
    async def broken(identity, *, limit, raise_on_unavailable):
        assert raise_on_unavailable is True
        raise EffectUnavailable("synthetic Redis outage")

    client = ScanClient(0, [("mako:chat:delivery:v1:" + "a" * 64).encode()])
    with pytest.raises(EffectUnavailable):
        await HistoryScanner(client, worker=SimpleNamespace(run_action=broken), classifier=lambda _: "unchanged").run_page()
    with pytest.raises(EffectUnavailable):
        await HistoryScanner(None).run_page()
