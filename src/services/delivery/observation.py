"""Best-effort, process-local observation of acknowledged group output."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GroupOutput:
    bot_id: str
    group_id: str
    message_id: str
    text: str
    category: str
    message_type: str = "text"
    mentions: tuple[str, ...] = ()
    reply_to_message_id: str | None = None


_observer: Callable[[GroupOutput], None] | None = None


def set_group_observer(observer: Callable[[GroupOutput], None] | None) -> None:
    """Replace the application observer; registration never accumulates handlers."""
    global _observer
    _observer = observer


def _describe_message(message):
    """Read only safe segment metadata, never media locations or raw CQ data."""
    if isinstance(message, str):
        return message[:2000], "text", (), None
    segments = [message] if hasattr(message, "type") else message
    text, kinds, mentions = [], [], []
    reply = None
    labels = {"image": "[图片]", "record": "[语音]", "video": "[视频]", "face": "[表情]"}
    for index, segment in enumerate(segments):
        if index >= 64:
            break
        kind = getattr(segment, "type", "unknown")
        data = getattr(segment, "data", {}) or {}
        if kind == "text":
            text.append(str(data.get("text", ""))[:2000])
        elif kind == "at":
            if len(mentions) < 32:
                mentions.append(str(data.get("qq", ""))[:100])
        elif kind == "reply":
            if data.get("id") is not None:
                reply = str(data["id"])[:100]
        else:
            text.append(labels.get(kind, "[非文本消息]"))
        if kind not in {"at", "reply"} and kind not in kinds:
            kinds.append(kind)
    return "".join(text)[:2000], "+".join(kinds)[:100] or "text", tuple(mentions), reply


def observe_group_output(bot_id, group_id, result, message, category: str) -> None:
    """No synthetic IDs, private output, network calls, retries or durable writes."""
    if _observer is None or not isinstance(result, dict):
        return
    message_id = result.get("message_id")
    if bot_id is None or group_id is None or message_id is None:
        return
    try:
        text, message_type, mentions, reply = _describe_message(message)
        _observer(GroupOutput(str(bot_id), str(group_id), str(message_id),
                              text, category, message_type, mentions, reply))
    except Exception:
        # Observation failure cannot change an already acknowledged delivery.
        logger.warning("Group output observation failed", exc_info=False)
