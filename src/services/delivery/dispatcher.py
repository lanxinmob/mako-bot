"""Shared, per-target outbound scheduling.

``dispatch`` returns True only after the callback completed successfully. Callers
own durable domain state and must only acknowledge/remove it on True. In
particular, reminders retain their persisted record until delivery succeeds.
Callbacks must send once and must not recursively dispatch to the same target.
"""

from __future__ import annotations

import asyncio
import inspect
import itertools
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Literal

from .observation import observe_group_output, observe_plugin_output

Category = Literal["chat", "autonomous", "news", "command", "reminder", "notice"]
Guard = Callable[[], bool | Awaitable[bool]]
_PRIORITY = {"reminder": 0, "command": 1, "notice": 2, "chat": 3, "autonomous": 4, "news": 4}
logger = logging.getLogger(__name__)


@dataclass
class _Target:
    busy: bool = False
    changed: asyncio.Event = field(default_factory=asyncio.Event)

    pending: list[tuple[int, int]] = field(default_factory=list)
    attempts: deque[float] = field(default_factory=deque)
    chat_attempts: deque[float] = field(default_factory=deque)
    unsolicited_attempts: deque[float] = field(default_factory=deque)
    last_attempt: float = float("-inf")
    touched: float = field(default_factory=time.monotonic)
    notices: dict[str, float] = field(default_factory=dict)
    errors: dict[str, float] = field(default_factory=dict)

    def notify(self) -> None:
        self.changed.set()
        self.changed = asyncio.Event()


class OutboundDispatcher:
    def __init__(self, *, spacing: float = 2.0, window: float = 60.0,
                 max_per_window: int = 8, max_pending: int = 64,
                 chat_max_per_window: int = 3, unsolicited_max_per_window: int = 1,
                 max_targets: int = 1024,
                 required_wait: float = 120.0, chat_wait: float = 6.0,
                 notice_ttl: float = 300.0, send_timeout: float = 30.0) -> None:
        self.spacing = max(0.0, spacing)
        self.window = max(0.001, window)
        self.max_per_window = max(1, max_per_window)
        self.max_pending = max(1, max_pending)
        self.chat_max_per_window = max(1, chat_max_per_window)
        self.unsolicited_max_per_window = max(1, unsolicited_max_per_window)
        self.max_targets = max(1, max_targets)
        self.required_wait = required_wait
        self.chat_wait = chat_wait
        self.notice_ttl = notice_ttl
        self.send_timeout = send_timeout
        self._targets: dict[tuple[str, str], _Target] = {}
        self._sequence = itertools.count()

    async def dispatch(self, target_type: str, target_id: int | str,
                       send: Callable[[], Awaitable[object]], *,
                       category: Category = "chat", guard: Guard | None = None,
                       notice_key: str | None = None) -> bool:
        if category not in _PRIORITY:
            raise ValueError(f"Unknown outbound category: {category}")
        if target_type not in {"group", "private"}:
            raise ValueError(f"Unknown outbound target: {target_type}")
        now = time.monotonic()
        # No tasks survive outside their callers; idle states are safe to evict.
        for key, item in list(self._targets.items()):
            if not item.pending and not item.busy and now - item.touched > max(self.window, self.notice_ttl):
                del self._targets[key]
        key = (target_type, str(target_id))
        if key not in self._targets and len(self._targets) >= self.max_targets:
            logger.warning("Outbound target limit reached; delivery not acknowledged target=%s", key)
            return False
        state = self._targets.setdefault(key, _Target())
        required = category in {"command", "reminder"}
        wait = self.required_wait if required else self.chat_wait if category == "chat" else 0.0
        deadline = now + max(0.0, wait)
        ticket = (_PRIORITY[category], next(self._sequence))
        state.touched = now
        if wait <= 0 and state.busy:
            return False
        if len(state.pending) >= self.max_pending:
            logger.warning("Outbound queue full target=%s category=%s; delivery not acknowledged", key, category)
            return False
        state.pending.append(ticket)
        state.notify()
        owns_slot = False
        try:
            while True:
                changed = state.changed
                now = time.monotonic()
                state.notices = {k: v for k, v in state.notices.items() if v > now}
                if notice_key and notice_key in state.notices:
                    return False
                for attempts in (state.attempts, state.chat_attempts, state.unsolicited_attempts):
                    while attempts and now - attempts[0] >= self.window:
                        attempts.popleft()
                delay = max(0.0, state.last_attempt + self.spacing - now)
                if len(state.attempts) >= self.max_per_window:
                    delay = max(delay, state.attempts[0] + self.window - now)
                category_attempts = (state.chat_attempts if category == "chat" else
                                     state.unsolicited_attempts if category in {"autonomous", "news"} else None)
                category_limit = self.chat_max_per_window if category == "chat" else self.unsolicited_max_per_window
                if category_attempts is not None and len(category_attempts) >= category_limit:
                    delay = max(delay, category_attempts[0] + self.window - now)
                if wait > 0 and now > deadline:
                    if required:
                        logger.warning("Outbound wait expired target=%s category=%s; delivery not acknowledged", key, category)
                    return False
                if not state.busy and ticket == min(state.pending) and delay <= 0:
                    state.busy = True
                    owns_slot = True
                    break
                remaining = deadline - now
                if remaining <= 0:
                    if required:
                        logger.warning("Outbound wait expired target=%s category=%s; delivery not acknowledged", key, category)
                    return False
                timeout = min(remaining, delay) if delay > 0 and not state.busy else remaining
                waiter = asyncio.create_task(changed.wait())
                try:
                    # asyncio.wait preserves caller cancellation even when the
                    # event completes simultaneously on Python 3.10.
                    await asyncio.wait({waiter}, timeout=timeout)
                finally:
                    waiter.cancel()
                    await asyncio.gather(waiter, return_exceptions=True)
            # The event-loop-owned slot covers guard and send; waiting callers
            # need no lock to time out or cancel while the API is pending.
            loop = asyncio.get_running_loop()
            sending = asyncio.Event()
            send_deadline = None
            aborted = False

            async def execute():
                nonlocal send_deadline
                if guard is not None:
                    try:
                        allowed = guard()
                        if inspect.isawaitable(allowed):
                            allowed = await allowed
                    except Exception:
                        logger.warning("Outbound guard failed target=%s category=%s; delivery not acknowledged", key, category)
                        return False
                    if not allowed:
                        if required:
                            logger.warning("Outbound guard rejected target=%s category=%s; delivery not acknowledged", key, category)
                        return False
                if aborted:
                    return False
                # No task switch between the sole guard and entering send.
                send_deadline = loop.time() + self.send_timeout
                sending.set()
                state.last_attempt = time.monotonic()
                state.attempts.append(state.last_attempt)
                if category_attempts is not None:
                    category_attempts.append(state.last_attempt)
                try:
                    result = await send()
                    if result is False:
                        raise RuntimeError("send callback reported failure")
                    return True
                finally:
                    state.last_attempt = time.monotonic()

            execution = asyncio.create_task(execute())
            phase = asyncio.create_task(sending.wait())
            try:
                await asyncio.wait({execution, phase}, timeout=max(0, self.send_timeout),
                                   return_when=asyncio.FIRST_COMPLETED)
                if not execution.done() and send_deadline is not None:
                    await asyncio.wait({execution}, timeout=max(0, send_deadline - loop.time()))
                if not execution.done():
                    raise asyncio.TimeoutError()
                if not execution.result():
                    return False
            except Exception as exc:
                if send_deadline is None:
                    logger.warning("Outbound guard failed target=%s category=%s; delivery not acknowledged", key, category)
                    return False
                error_key = type(exc).__name__
                now = time.monotonic()
                state.errors = {k: v for k, v in state.errors.items() if v > now}
                if error_key not in state.errors:
                    logger.warning("Outbound failed target=%s category=%s error=%s; delivery not acknowledged", key, category, error_key)
                    state.errors[error_key] = now + self.notice_ttl
                if notice_key:
                    state.notices[notice_key] = now + self.notice_ttl
                return False
            finally:
                # A timed-out guard may swallow cancellation; it must not send.
                aborted = True
                execution.cancel()
                phase.cancel()
                cleanup = asyncio.gather(execution, phase, return_exceptions=True)
                cancelled = False
                while not cleanup.done():
                    try:
                        await asyncio.shield(cleanup)
                    except asyncio.CancelledError:
                        cancelled = True
                if cancelled:
                    raise asyncio.CancelledError()
            if notice_key:
                state.notices[notice_key] = time.monotonic() + self.notice_ttl
            return True
        finally:
            state.pending.remove(ticket)
            state.touched = time.monotonic()
            if owns_slot:
                state.busy = False
            state.notify()


outbound = OutboundDispatcher()
_configured = False


def configure_outbound(settings=None) -> None:
    """Apply settings without replacing live locks, queues, or usage counters."""
    global _configured
    if settings is None:
        from src.core.config import get_settings
        settings = get_settings()
    fields = {
        "spacing": ("outbound_min_spacing_seconds", 2.0, float, 0.0),
        "max_per_window": ("outbound_max_per_minute", 8, int, 1),
        "chat_max_per_window": ("outbound_chat_max_per_minute", 3, int, 1),
        "unsolicited_max_per_window": ("outbound_unsolicited_max_per_minute", 1, int, 1),
        "max_pending": ("outbound_max_pending_per_target", 64, int, 1),
        "max_targets": ("outbound_max_targets", 1024, int, 1),
        "required_wait": ("outbound_required_wait_seconds", 120.0, float, 0.0),
    }
    for attribute, (name, default, cast, minimum) in fields.items():
        setattr(outbound, attribute, max(minimum, cast(getattr(settings, name, default))))
    _configured = True


async def dispatch(target_type: str, target_id: int | str,
                   send: Callable[[], Awaitable[object]], *, category: Category = "chat",
                   guard: Guard | None = None, notice_key: str | None = None) -> bool:
    if not _configured:
        configure_outbound()
    return await outbound.dispatch(target_type, target_id, send, category=category,
                                   guard=guard, notice_key=notice_key)


def acknowledged_result(result: object) -> bool:
    """Normalize an explicit adapter acknowledgement; absence is not success."""
    return result is True or (isinstance(result, dict) and result.get("message_id") is not None)


async def send_to_event(matcher, event, message, *, category: Category = "command",
                        guard: Guard | None = None, notice_key: str | None = None) -> bool:
    group_id = getattr(event, "group_id", None)
    async def send():
        result = await matcher.send(message)
        acknowledged = acknowledged_result(result)
        if acknowledged:
            observe_plugin_output(getattr(event, "self_id", None),
                                  "group" if group_id is not None else "private",
                                  group_id if group_id is not None else event.user_id,
                                  result, message, category)
        if acknowledged and group_id is not None:
            observe_group_output(getattr(event, "self_id", None), group_id,
                                 result, message, category)
        return acknowledged

    sent = await dispatch("group" if group_id is not None else "private",
                          group_id if group_id is not None else event.user_id,
                          send, category=category,
                          guard=guard, notice_key=notice_key)
    if not sent and category == "command" and notice_key is None:
        await send_notice(matcher, event, "这次回复的送达状态未确认；操作可能已经执行，请查询状态后再决定是否重试。",
                          notice_key="outbound.command_failed")
    return sent


send_to_matcher = send_to_event


async def send_to_group(bot, group_id: int, message, *, category: Category = "autonomous",
                        guard: Guard | None = None, notice_key: str | None = None) -> bool:
    async def send():
        result = await bot.send_group_msg(group_id=group_id, message=message)
        acknowledged = acknowledged_result(result)
        if acknowledged:
            observe_plugin_output(getattr(bot, "self_id", None), "group", group_id,
                                  result, message, category)
            observe_group_output(getattr(bot, "self_id", None), group_id,
                                 result, message, category)
        return acknowledged

    return await dispatch("group", group_id, send,
                          category=category, guard=guard, notice_key=notice_key)


async def send_to_private(bot, user_id: int, message, *, category: Category = "command",
                          guard: Guard | None = None, notice_key: str | None = None) -> bool:
    async def send():
        result = await bot.send_private_msg(user_id=user_id, message=message)
        acknowledged = acknowledged_result(result)
        if acknowledged:
            observe_plugin_output(getattr(bot, "self_id", None), "private", user_id,
                                  result, message, category)
        return acknowledged

    return await dispatch("private", user_id, send,
                          category=category, guard=guard, notice_key=notice_key)


async def finish_to_event(matcher, event, message, **kwargs) -> None:
    await send_to_event(matcher, event, message, **kwargs)
    await matcher.finish()


async def send_notice(matcher, event, message, *, notice_key: str,
                      guard: Guard | None = None) -> bool:
    """Coalesce outage notices without treating suppression as delivery."""
    return await send_to_event(matcher, event, message, category="command",
                               notice_key=notice_key, guard=guard)
