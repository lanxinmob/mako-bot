"""Pure policies shared by the chat transport and service layers.

The functions in this module deliberately know nothing about NoneBot.  They are
the small, deterministic pieces of the chat request pipeline and can therefore
be tested without starting a bot or connecting to Redis.
"""

from __future__ import annotations

from dataclasses import dataclass
from random import random
from typing import Literal, Optional

from src.core.config import Settings, get_settings


ReplyMode = Literal["micro", "short", "normal", "deep"]


@dataclass(frozen=True)
class ReplyPlan:
    """The visible length and timing contract for one chat reply."""

    mode: ReplyMode
    max_chars: int
    max_tokens: int
    latency_min: float
    latency_max: float
    social_state: str = "normal"

    def prompt_contract(self) -> str:
        contracts = {
            "micro": "只用一句自然的话回应，优先保留情绪和态度，不要补齐无关建议。",
            "short": "用一到三句自然表达回应；保留茉子的判断，只有确实有帮助时才给建议。",
            "normal": "按需要展开共情、判断和建议，但不要为了套结构而重复或填充空话。",
            "deep": "可以完整解释并给出具体建议；保持清晰、有重点，不要把所有内容写成泛泛安慰。",
        }
        return contracts[self.mode]


def select_reply_plan(
    text: str,
    *,
    message_type: str,
    directed: bool,
    has_image: bool = False,
    has_audio: bool = False,
    has_tool_result: bool = False,
    fast_exchange: bool = False,
    settings: Optional[Settings] = None,
) -> ReplyPlan:
    """Choose response granularity without changing Mako's emotional stance."""

    settings = settings or get_settings()
    compact = "".join(str(text or "").split())
    deep_markers = (
        "为什么", "怎么做", "如何", "分析", "比较", "区别", "解释", "计划",
        "建议", "原因", "详细", "认真说", "难过", "焦虑", "害怕", "崩溃",
        "好累", "很累", "委屈", "生气", "失眠", "压力", "烦死", "撑不住",
    )
    lightweight = (
        len(compact) <= 24
        and not any(marker in compact for marker in deep_markers)
        and not any(mark in compact for mark in ("？", "?"))
    )

    if fast_exchange:
        mode: ReplyMode = "short"
        social_state = "rapid_exchange"
    elif has_image or has_audio or has_tool_result or any(marker in compact for marker in deep_markers):
        mode = "deep"
        social_state = "normal"
    elif lightweight:
        mode = "micro"
        social_state = "normal"
    elif message_type == "group" and not directed:
        mode = "short"
        social_state = "normal"
    elif message_type == "private" or directed:
        mode = "normal"
        social_state = "normal"
    else:
        mode = "short"
        social_state = "normal"

    limits = {
        "micro": (settings.chat_reply_max_chars_micro, settings.chat_reply_max_tokens_micro),
        "short": (settings.chat_reply_max_chars_short, settings.chat_reply_max_tokens_short),
        "normal": (settings.chat_reply_max_chars_normal, settings.chat_reply_max_tokens_normal),
        "deep": (settings.chat_reply_max_chars_deep, settings.chat_reply_max_tokens_deep),
    }
    delays = {
        "micro": (0.8, 2.5),
        "short": (1.2, 4.0),
        "normal": (1.8, 6.0),
        "deep": (2.5, 8.0),
    }
    max_chars, max_tokens = limits[mode]
    latency_min, latency_max = delays[mode]
    return ReplyPlan(mode, max_chars, max_tokens, latency_min, latency_max, social_state)


def remaining_reply_delay(
    plan: ReplyPlan,
    elapsed_seconds: float,
    *,
    sample: Optional[float] = None,
) -> float:
    """Return only the delay still needed to reach a natural total latency."""

    fraction = random() if sample is None else min(1.0, max(0.0, sample))
    target = plan.latency_min + (plan.latency_max - plan.latency_min) * fraction
    return max(0.0, target - max(0.0, elapsed_seconds))


def truncate_reply(text: str, max_chars: int) -> str:
    """Trim at a sentence boundary whenever the model exceeds its contract."""

    value = (text or "").strip()
    limit = max(1, max_chars)
    if len(value) <= limit:
        return value
    if limit == 1:
        return "…"
    content_limit = limit - 1
    boundary = content_limit
    for index in range(content_limit, max(1, int(content_limit * 0.55)), -1):
        if value[index - 1] in "。！？!?；;\n":
            boundary = index
            break
    return value[:boundary].rstrip(" ，,、") + "…"


@dataclass(frozen=True)
class ChatAddress:
    """The protocol-neutral identity of one incoming chat message."""

    message_type: str
    user_id: int
    group_id: Optional[int] = None

    @property
    def session_id(self) -> str:
        if self.message_type == "group" and self.group_id is not None:
            return f"group_{self.group_id}"
        if self.message_type == "private":
            return f"private_{self.user_id}"
        return f"user_{self.user_id}"


def should_reply(
    text: str,
    *,
    is_to_me: bool,
    random_chance: float,
    sample: Optional[float] = None,
) -> bool:
    """Apply the group-chat admission policy.

    Explicit mentions and name mentions always pass.  Other messages are
    admitted according to the configured probability.  ``sample`` is exposed
    for deterministic tests.
    """

    lowered = text.lower()
    if is_to_me or "茉子" in text or "mako" in lowered:
        return True
    chance = min(1.0, max(0.0, random_chance))
    return (random() if sample is None else sample) < chance


def should_record_message(
    *,
    message_type: str,
    directed: bool,
    will_reply: bool,
    record_undirected_group_messages: bool,
) -> bool:
    """Apply the privacy boundary before durable chat observation."""

    if message_type != "group":
        return True
    return directed or will_reply or record_undirected_group_messages


def compact_text(value: object, max_chars: int = 160) -> str:
    compact = " ".join(str(value or "").split())
    if len(compact) <= max_chars:
        return compact
    return compact[:max_chars].rstrip() + "..."
