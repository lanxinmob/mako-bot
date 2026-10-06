"""Bind the request snapshot, one transport attempt and frozen history effects."""
import asyncio
from dataclasses import dataclass
from datetime import datetime
import logging
import secrets
import time

from src.services.persistence.history_commit.delivery import HistoryDeliveryStore
from src.services.persistence.history_commit.plans import build_plan, timestamp_ms
from src.services.persistence.history_commit.snapshot import HistorySnapshots
from .worker import HistoryWorker


logger = logging.getLogger(__name__)


class HistoryNotAdmitted(RuntimeError):
    """Missing durable history evidence pauses generation or this reply's send."""


@dataclass(frozen=True)
class HistoryReceipt:
    action_id: str
    acknowledged: bool
    sent_recorded: bool


class ChatHistoryRuntime:
    def __init__(self, storage, settings):
        self.storage, self.settings = storage, settings

    async def read(self, session_id):
        try:
            client = await asyncio.to_thread(lambda: self.storage.redis)
            return await asyncio.to_thread(HistorySnapshots(client).read, session_id)
        except Exception as exc:
            raise HistoryNotAdmitted("durable history snapshot unconfirmed") from exc

    async def send(self, incoming, transport, request, reply) -> HistoryReceipt:
        try:
            client = await asyncio.to_thread(lambda: self.storage.redis)
            offset = datetime.now().astimezone().utcoffset()
            if offset is None:
                raise ValueError("local history offset unavailable")
            plan = build_plan(secrets.token_hex(32), request.history_snapshot,
                              bot_id=incoming.bot_id, user_id=request.user_id, group_id=request.group_id,
                              text=reply.text, history=reply.history,
                              max_history_turns=self.settings.max_history_turns,
                              global_max_records=max(1000, self.settings.global_memory_max_records),
                              utc_offset_seconds=int(offset.total_seconds()))
            store = HistoryDeliveryStore(client)
            token = await asyncio.to_thread(store.create, plan)
            if token is None:
                raise HistoryNotAdmitted("history plan creation not admitted")
        except Exception as exc:
            raise HistoryNotAdmitted("history plan persistence unconfirmed") from exc

        begin_attempted, acknowledged_at, recorded = False, None, False

        async def before_send():
            nonlocal begin_attempted
            if incoming.is_current is not None and not incoming.is_current():
                return False
            begin_attempted = True
            if await asyncio.to_thread(store.transition, plan.action_id, token, "begin") != "sending":
                return False
            # Persistence introduces an await after the dispatcher guard. Check
            # the exact frozen candidate again, without refreshing its token.
            return incoming.is_current is None or incoming.is_current()

        def on_ack():
            nonlocal acknowledged_at
            if acknowledged_at is None:
                acknowledged_at = timestamp_ms(time.time_ns() // 1000000)

        try:
            await transport.reply_recorded(reply.text, before_send=before_send, on_ack=on_ack)
        except Exception:
            if acknowledged_at is None:
                raise
            logger.warning("Chat transport post-ACK callback failed; preserving acknowledged delivery")
        finally:
            # No provider/transport retry here. Cancellation may leave an
            # in-flight store thread; preserve its evidence, never regrant begin.
            try:
                if acknowledged_at is not None:
                    result = await asyncio.to_thread(store.transition, plan.action_id, token, "sent",
                                                     delivered_at_ms=acknowledged_at)
                    recorded = result == "sent"
                else:
                    await asyncio.to_thread(store.transition, plan.action_id, token,
                                            "unknown" if begin_attempted else "reject")
            except Exception:
                logger.warning("Chat send settlement unconfirmed; preserved without resending")
        return HistoryReceipt(plan.action_id, acknowledged_at is not None, recorded)

    async def consume(self, receipt: HistoryReceipt) -> dict[str, str]:
        status = {"history_session": "unknown", "history_global": "unknown"}
        if not isinstance(receipt, HistoryReceipt) or not receipt.acknowledged:
            return status
        try:
            client = await asyncio.to_thread(lambda: self.storage.redis)
            worker = HistoryWorker(client)
            await worker.run_action(receipt.action_id)
            snapshot = await asyncio.to_thread(worker.store.inspect, receipt.action_id)
            if snapshot is not None and snapshot.delivery.state == "sent":
                status.update({"history_" + task.kind: task.state for task in snapshot.tasks})
        except Exception:
            logger.warning("Chat history consumption unconfirmed; preserved for recovery")
        return status
