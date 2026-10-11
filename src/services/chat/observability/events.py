"""Safe hooks: failures are limited to visibility, never chat behavior."""
import asyncio
from .store import RhythmTraceStore

store = RhythmTraceStore()


def observe(bot, group, message):
    try:
        store.observe(bot, group, message)
    except Exception:
        pass


def update(bot, group, message, **changes):
    try:
        store.update(bot, group, message, **changes)
    except Exception:
        pass


def phase(incoming, stage, reason=None):
    if incoming.address.group_id is not None and incoming.work_kind == "chat":
        changes = {"stage": stage}
        if reason:
            changes["outcome_reason_code"] = reason
        elif stage == "generating":
            changes["outcome_reason_code"] = None
        if stage == "candidate":
            # A late generation completion cannot erase an observed cancellation.
            changes["preserve_canceled"] = True
        update(incoming.bot_id, str(incoming.address.group_id), incoming.message_id, **changes)


def decision(bot, value, *, owner):
    if value.target_message_id is None or not value.disposable:
        return
    changes = dict(action=value.action, reason_code=value.reason,
                   wait_ms=round(value.wait_seconds * 1000) if value.action == "wait" else None)
    if value.target_message_id == owner:
        changes["stage"] = {"ignore": "finished", "wait": "waiting", "reply": "candidate"}[value.action]
    update(bot, value.group_id, value.target_message_id, **changes)


async def tracked_send(matcher, payload, bot, event, category):
    if (category != "chat" or getattr(event, "group_id", None) is None
            or getattr(bot, "self_id", None) is None or getattr(event, "message_id", None) is None):
        return await matcher.send(payload)
    from src.services.delivery.dispatcher import acknowledged_result
    from nonebot.adapters.onebot.v11.exception import ActionFailed
    args = (str(bot.self_id), str(event.group_id), str(event.message_id))
    update(*args, send_state="in_flight")
    try:
        result = await matcher.send(payload)
    except ActionFailed:
        update(*args, send_state="failed", stage="finished")
        raise
    except BaseException:
        update(*args, send_state="unknown")
        raise
    update(*args, send_state="confirmed" if acknowledged_result(result) else "unknown", stage="finished")
    return result
