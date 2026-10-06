import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.services.chat.pipeline.completion import complete_sent_reply
from test.chat.history_delivery.fixtures import RECEIPT, history_double


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["history", "cost", "attachment", None])
async def test_primary_commit_precedes_attachment_and_reports_partial_results(failure):
    order = []

    def operation(name):
        def run(*args):
            order.append(name)
            if name == failure:
                raise RuntimeError("synthetic failure")
        return run

    async def extra(payload):
        operation("attachment")()
        return True

    async def history(receipt):
        operation("history")()
        return {"history_session": "complete", "history_global": "complete"}

    services = SimpleNamespace(chat_rhythm=Mock(), audit=Mock(),
        history_delivery=SimpleNamespace(consume=history),
        governance=SimpleNamespace(consume_cost=operation("cost")))
    incoming = SimpleNamespace(address=SimpleNamespace(session_id="group_1", user_id=2, group_id=1))
    request = SimpleNamespace(reply_plan=SimpleNamespace(mode="short"))
    cost_status = "unknown" if failure == "cost" else "call_completed"
    await complete_sent_reply(services, incoming, SimpleNamespace(extra=extra),
        SimpleNamespace(extra_messages=["image"]), request, SimpleNamespace(text="sent"), cost_status, 0,
        history_receipt=RECEIPT)
    assert order == ["history", "attachment"]
    data = services.audit.progress.call_args.args[2]
    assert data["history"] == ("unknown" if failure == "history" else "confirmed")
    assert data["cost"] == cost_status
    assert data["attachments_failed"] == int(failure == "attachment")


@pytest.mark.asyncio
async def test_cancelled_commit_records_unknown_without_retry(monkeypatch):
    from src.services.chat.pipeline import completion

    entered = asyncio.Event()
    async def consume(*args):
        entered.set()
        await asyncio.Event().wait()
    services = SimpleNamespace(chat_rhythm=Mock(), audit=Mock(),
                               history_delivery=SimpleNamespace(consume=consume), governance=Mock())
    incoming = SimpleNamespace(address=SimpleNamespace(session_id="s", user_id=2, group_id=1))
    task = asyncio.create_task(complete_sent_reply(services, incoming, SimpleNamespace(extra=AsyncMock()),
        SimpleNamespace(extra_messages=[]), SimpleNamespace(reply_plan=SimpleNamespace(mode="short")),
        SimpleNamespace(text="sent"), "call_completed", 0, history_receipt=RECEIPT))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    data = services.audit.progress.call_args.args[2]
    assert data["history"] == "unknown" and data["cost"] == "call_completed"


@pytest.mark.parametrize("status", ["complete", "pending", "unknown", "needs_review"])
def test_generation_cost_audit_does_not_charge_again(status):
    from src.services.chat.pipeline import execution
    services = SimpleNamespace(governance=Mock(), audit=Mock())
    incoming = SimpleNamespace(address=SimpleNamespace(user_id=2, group_id=1))
    assert execution.report_generation_cost(services, incoming, status) == status
    services.governance.consume_cost.assert_not_called()
    data = services.audit.progress.call_args.args[2]
    assert data["cost"] == status


@pytest.mark.asyncio
async def test_attachment_receipts_must_be_explicit_without_replaying_primary():
    services = SimpleNamespace(chat_rhythm=Mock(), audit=Mock(), chat_engine=Mock(),
                               history_delivery=history_double())
    incoming = SimpleNamespace(address=SimpleNamespace(session_id="s", user_id=2, group_id=1))
    transport = SimpleNamespace(extra=AsyncMock(side_effect=[None, False, True]))
    await complete_sent_reply(services, incoming, transport,
        SimpleNamespace(extra_messages=["missing", "rejected", "confirmed"]),
        SimpleNamespace(reply_plan=SimpleNamespace(mode="short")),
        SimpleNamespace(text="sent"), "complete", 0, history_receipt=RECEIPT)
    services.history_delivery.consume.assert_awaited_once_with(RECEIPT)
    services.chat_engine.commit.assert_not_called()
    assert transport.extra.await_count == 3
    data = services.audit.progress.call_args.args[2]
    assert data["attachments_sent"] == 1 and data["attachments_failed"] == 2
