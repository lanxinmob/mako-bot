"""Narrow protocol doubles; durability itself is covered with isolated Redis."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

from src.services.chat.history_delivery.runtime import HistoryReceipt
from src.services.persistence.history_commit.snapshot import HistorySnapshot


RECEIPT = HistoryReceipt("a" * 64, True, True)


def history_double(*, order=None):
    async def read(session):
        return HistorySnapshot(session, "missing", None)

    async def send(incoming, transport, request, reply):
        acknowledged = await transport.reply(reply.text) is True
        return HistoryReceipt(RECEIPT.action_id, acknowledged, acknowledged)

    async def consume(receipt):
        if order is not None:
            order.append("commit")
        return {"history_session": "complete", "history_global": "complete"}

    return SimpleNamespace(read=AsyncMock(side_effect=read), send=AsyncMock(side_effect=send),
                           consume=AsyncMock(side_effect=consume))
