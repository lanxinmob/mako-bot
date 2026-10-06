"""Observe before locking; carry one disposable group candidate to delivery."""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, replace

from src.services.chat.group.models import GroupEvent
from src.services.chat.group.service import GroupConversationService
from src.services.tools.intent import decide_intents
from src.utils.message import NormalizedMessage


@dataclass
class ToolReceipt:
    user_id: str
    digest: str
    expires_at: float | None
    claimed: bool = False


def _digest(media):
    return hashlib.sha256(json.dumps(
        vars(media), sort_keys=True, ensure_ascii=False,
    ).encode("utf-8")).hexdigest()


def _explicit_tool(media):
    intents = decide_intents(media.plain_text, has_image=bool(media.image_urls),
                             has_audio=bool(media.audio_urls), face_ids=media.face_ids)
    return any(item.name not in {"search.web", "search.summarize_url", "image.describe"}
               for item in intents)


class GroupParticipation:
    def __init__(self, *, clock=time.monotonic, tool_capacity=1024, group_tool_capacity=64):
        self._bots: dict[str, GroupConversationService] = {}
        self._tool_receipts: dict[tuple[str, str, str], ToolReceipt] = {}
        self._clock = clock
        self._tool_capacity = tool_capacity
        self._group_tool_capacity = group_tool_capacity

    def _expire_receipts(self):
        now = self._clock()
        for key, receipt in tuple(self._tool_receipts.items()):
            if receipt.expires_at is not None and receipt.expires_at <= now:
                del self._tool_receipts[key]

    def service(self, bot_id: str) -> GroupConversationService:
        if bot_id not in self._bots:
            if len(self._bots) >= 16:
                raise RuntimeError("group observer bot capacity exceeded")
            self._bots[bot_id] = GroupConversationService(bot_user_id=bot_id)
        return self._bots[bot_id]

    def observe(self, bot_id: str, event: GroupEvent, normalized=None):
        service = self.service(bot_id)
        snapshot = service.observe(event)
        self._expire_receipts()
        state = service.window.get(event.group_id)
        media = normalized if normalized is not None else NormalizedMessage(plain_text=event.text)
        # Authorize this event before asynchronous metadata lookup lets a newer
        # group message replace the conversation's current target.
        if (state is None or service.policy.gate(event, state) != "direct_call"
                or event.user_id == bot_id or not _explicit_tool(media)):
            return snapshot
        key = (bot_id, event.group_id, event.message_id)
        if key in self._tool_receipts:
            return snapshot  # Replays cannot refresh or replace an existing receipt.
        count = sum(item[:2] == key[:2] for item in self._tool_receipts)
        if len(self._tool_receipts) < self._tool_capacity and count < self._group_tool_capacity:
            self._tool_receipts[key] = ToolReceipt(event.user_id, _digest(media), self._clock() + 600)
        return snapshot

    def observe_output(self, output):
        # Unsolicited/tool output is context, never a conversational lease.
        kind = "reminder" if output.category == "reminder" else "tool"
        return self.service(output.bot_id).record_outbound(GroupEvent(
            output.group_id, output.message_id, output.bot_id,
            text=output.text, is_bot=True, kind=kind,
            message_type=output.message_type, mentions=output.mentions,
            reply_to_message_id=output.reply_to_message_id,
        ))

    async def prepare(self, incoming, transport):
        service = self.service(incoming.bot_id)
        group_id = str(incoming.address.group_id)
        def read_context():
            return service.snapshot(group_id).render()

        def observe_sent(result, text, *, kind="chat", addressed=True):
            message_id = result.get("message_id") if isinstance(result, dict) else None
            if message_id is not None:
                service.record_outbound(GroupEvent(
                    group_id, str(message_id), incoming.bot_id, text=text,
                    is_bot=True, kind=kind, reply_to_message_id=incoming.message_id,
                    reply_to_user_id=str(incoming.address.user_id) if addressed else None,
                ))

        self._expire_receipts()
        key = (incoming.bot_id, group_id, incoming.message_id)
        receipt = self._tool_receipts.get(key)
        if receipt is not None:
            if (receipt.claimed or receipt.user_id != str(incoming.address.user_id)
                    or receipt.digest != _digest(incoming.normalized)):
                return None
            receipt.claimed = True
            receipt.expires_at = None  # Pin while waiting/executing; never reclaim active work.

            def finish_tool():
                if receipt.expires_at is None:
                    receipt.expires_at = self._clock() + 600

            transport.cancel_candidate = finish_tool
            transport.category = "command"
            transport.on_sent = lambda result, text: observe_sent(result, text, kind="tool")
            return replace(incoming, directed=True, work_kind="tool",
                           group_context=read_context(), read_group_context=read_context)

        if _explicit_tool(incoming.normalized):
            # Never borrow a newer target's authorization or downgrade rejected
            # tool work to disposable chat. Notifications use the shared limiter.
            if incoming.directed:
                await transport.notice("这条工具请求未被接纳或已过期，本次没有执行。")
            return None

        while True:
            snapshot = service.snapshot(group_id)
            decision = service.select_decision(snapshot)
            if decision.target_message_id != incoming.message_id or decision.action == "ignore":
                return None
            if decision.action == "wait":
                await asyncio.sleep(decision.wait_seconds)
                continue
            candidate = service.begin_candidate(decision)
            if candidate is None:
                return None
            break

        def current():
            return service.candidate_is_current(candidate)

        def refresh_before_generation():
            nonlocal candidate
            if service.candidate_is_current(candidate):
                return True
            decision = service.select_decision(service.snapshot(group_id))
            refreshed = service.revalidate_candidate(candidate, decision)
            if refreshed is None:
                return False
            candidate = refreshed
            return True

        def sent(result, text):
            marked = service.mark_sent(candidate)
            observe_sent(result, text, addressed=marked)

        transport.guard = current
        transport.on_sent = sent
        transport.cancel_candidate = lambda: service.cancel_candidate(candidate)
        return replace(incoming, group_context=snapshot.render(), is_current=current,
                       read_group_context=read_context,
                       refresh_before_generation=refresh_before_generation)
