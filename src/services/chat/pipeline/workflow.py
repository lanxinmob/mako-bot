from __future__ import annotations
import asyncio
import time
from nonebot.log import logger
from src.services.chat.policy import remaining_reply_delay
from src.services.chat.policy import select_reply_plan
from .models import ChatInput, ChatServices, ChatTransport, PreSendDiscard

from dataclasses import dataclass, replace
from .admission import admit
from .execution import execute
from .participation import GroupParticipation
from .group_memory import GroupMemoryObserver
from src.services.chat.observability.events import phase


@dataclass
class PendingBatch:
    version: int
    texts: list[str]
    incoming: ChatInput
    transport: ChatTransport


class ChatWorkflow:
    def __init__(self, services: ChatServices):
        self.services = services
        self.participation = GroupParticipation()
        self.group_memory = GroupMemoryObserver(services)
        self._locks: dict[str, asyncio.Lock] = {}
        self._pending: dict[tuple[str, int], PendingBatch] = {}
        self._guard: asyncio.Lock | None = None

    def _batch_guard(self):
        if self._guard is None:
            self._guard = asyncio.Lock()
        return self._guard

    async def handle(self, incoming: ChatInput, transport: ChatTransport):
        if incoming.address.group_id is not None and incoming.message_id:
            original = incoming
            try:
                incoming = await self.participation.prepare(incoming, transport)
            except asyncio.CancelledError:
                phase(incoming, "canceled", "task_canceled")
                raise
            if incoming is None:
                return
            lock = self._locks.setdefault(incoming.address.session_id, asyncio.Lock())
            try:
                async with lock:
                    if (incoming.refresh_before_generation is not None
                            and not incoming.refresh_before_generation()):
                        return
                    if incoming.is_current is None or incoming.is_current():
                        outcome = await self.handle_locked(incoming, transport)
                        # Only a proven pre-transport discard can regenerate once.
                        # Unknown/acknowledged sends and replaced/closed/expired
                        # requests never enter this branch.
                        if isinstance(outcome, PreSendDiscard):
                            prior_memory = getattr(transport, 'memory_view', None)
                            if prior_memory is not None and not prior_memory.current():
                                return
                            service = self.participation.service(incoming.bot_id)
                            state = service.window.get(str(incoming.address.group_id))
                            if (state and state.pending_target and
                                    state.pending_target.message_id == incoming.message_id):
                                transport.cancel_candidate()
                                refreshed = await self.participation.prepare(original, transport)
                                if prior_memory is not None and not prior_memory.current():
                                    return
                                if refreshed is not None and refreshed.is_current():
                                    incoming = refreshed
                                    # Admission, relationship absorption and rhythm
                                    # accounting already ran; do not repeat them.
                                    await execute(self.services, incoming, transport,
                                                  self.services.make_tools(), outcome.rhythm)
            except asyncio.CancelledError:
                phase(incoming, "canceled", "task_canceled")
                raise
            finally:
                transport.cancel_candidate()
                phase(incoming, "finished")
            return
        delay = self.services.settings.chat_reply_debounce_seconds
        media = incoming.normalized
        can_batch = bool(delay > 0 and incoming.text and len(incoming.text) <= 80
                         and not media.image_urls and not media.audio_urls and not media.face_ids)
        if can_batch:
            key = (incoming.address.session_id, incoming.address.user_id)
            async with self._batch_guard():
                previous = self._pending.get(key)
                version = previous.version + 1 if previous else 1
                texts = [*previous.texts, incoming.text] if previous else [incoming.text]
                if previous:
                    incoming = replace(incoming, started_at=previous.incoming.started_at)
                batch = PendingBatch(version, texts, incoming, transport)
                self._pending[key] = batch
            try:
                await asyncio.sleep(delay)
                async with self._batch_guard():
                    if self._pending.get(key) is not batch:
                        return
                    self._pending.pop(key)
            finally:
                # No await here: cleanup is atomic on this workflow's event loop,
                # including repeated cancellation while waiting for the guard.
                # Identity also prevents an old sleeper claiming a reused version.
                if self._pending.get(key) is batch:
                    self._pending.pop(key)
            incoming = replace(batch.incoming, text="\n".join(batch.texts))
            transport = batch.transport
        lock = self._locks.setdefault(incoming.address.session_id, asyncio.Lock())
        async with lock:
            await self.handle_locked(incoming, transport)

    async def handle_locked(self, incoming: ChatInput, transport: ChatTransport):
        services = self.services
        tool_executor = services.make_tools()
        decision = await admit(services, incoming, transport)
        if decision is None:
            return
        will_reply, rhythm = decision.will_reply, decision.rhythm
        address = incoming.address
        user_text = incoming.text
        nickname = incoming.nickname
        directed = incoming.directed
        request_started_at = incoming.started_at

        if not will_reply:
            return
        if rhythm and rhythm.boundary:
            boundary_plan = select_reply_plan(
                user_text,
                message_type=incoming.address.message_type,
                directed=directed,
                fast_exchange=True,
            )
            delay = remaining_reply_delay(
                boundary_plan,
                time.perf_counter() - request_started_at,
            )
            if delay:
                await asyncio.sleep(delay)
            boundary_text = services.chat_rhythm.boundary_text()
            if await transport.reply(boundary_text) is False:
                return
            services.chat_rhythm.mark_sent(
                address.session_id,
                sender_id=incoming.address.user_id,
                boundary=True,
            )
            services.audit.progress(
                "chat_rhythm_boundary",
                "快速往返达到阈值，茉子主动收束并进入冷却。",
                {
                    "user_id": incoming.address.user_id,
                    "group_id": address.group_id,
                    "known_bot": rhythm.known_bot,
                    "automation_score": rhythm.automation_score,
                    "rapid_turns": rhythm.rapid_turns,
                },
            )
            return
        if await transport.reminder(address, user_text):
            return

        try:
            absorb = getattr(services.relationship, 'absorb_incoming', None)
            if callable(absorb):
                await absorb(incoming)
            else:
                await asyncio.to_thread(services.relationship.absorb_user_message,
                                        incoming.address.user_id, nickname, user_text)
        except Exception as exc:
            logger.warning(f"关系记忆吸收失败，继续普通聊天: {exc}")

        return await execute(services, incoming, transport, tool_executor, rhythm)
