from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from src.core.config import get_settings
from src.models.schemas import OutboundMessageRecord
from src.services.storage import StorageService


_STYLE_FILLERS = (
    "茉子大人",
    "茉子",
    "大家",
    "各位",
    "呀",
    "啦",
    "哦",
    "呢",
    "嘛",
)
LOCAL_TZ = ZoneInfo("Asia/Shanghai")
_TIME_GREETINGS = ("早上好", "早安", "上午好", "中午好", "下午好", "晚上好")


def align_time_greeting(text: str, now: Optional[datetime] = None) -> str:
    current = now or datetime.now(LOCAL_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=LOCAL_TZ)
    hour = current.astimezone(LOCAL_TZ).hour
    if 5 <= hour < 11:
        accepted, preferred = {"早上好", "早安", "上午好"}, "早上好"
    elif 11 <= hour < 14:
        accepted, preferred = {"中午好"}, "中午好"
    elif 14 <= hour < 18:
        accepted, preferred = {"下午好"}, "下午好"
    else:
        accepted, preferred = {"晚上好"}, "晚上好"
    if any(token in text for token in accepted):
        return text
    corrected = text
    for token in _TIME_GREETINGS:
        corrected = corrected.replace(token, preferred)
    return corrected


@dataclass(frozen=True)
class DedupDecision:
    allowed: bool
    reason: str = ""
    similarity: float = 0.0
    matched_message_id: Optional[str] = None


def normalize_outbound_text(text: str) -> str:
    value = unicodedata.normalize("NFKC", text or "").lower()
    value = re.sub(r"\[[^\]]+\]", " ", value)
    value = re.sub(r"https?://\S+", " ", value)
    for filler in _STYLE_FILLERS:
        value = value.replace(filler, "")
    return "".join(re.findall(r"[\u4e00-\u9fff]|[a-z0-9]+", value))


def _character_ngrams(text: str, size: int = 2) -> set[str]:
    if not text:
        return set()
    if len(text) <= size:
        return {text}
    return {text[index : index + size] for index in range(len(text) - size + 1)}


def outbound_similarity(left: str, right: str) -> float:
    a = normalize_outbound_text(left)
    b = normalize_outbound_text(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    sequence = SequenceMatcher(None, a, b).ratio()
    a_grams = _character_ngrams(a)
    b_grams = _character_ngrams(b)
    dice = (
        2.0 * len(a_grams & b_grams) / (len(a_grams) + len(b_grams))
        if a_grams and b_grams
        else 0.0
    )
    return max(sequence, dice)


def canonical_intent(intent: str, text: str = "") -> str:
    value = re.sub(r"[^a-z0-9_\-]", "", (intent or "").strip().lower())
    aliases = {
        "daily_greeting": "greeting",
        "morning": "greeting",
        "hello": "greeting",
        "checkin": "check_in",
        "followup": "check_in",
        "follow_up": "check_in",
        "news": "daily_digest",
        "digest": "daily_digest",
    }
    opening = text[:32]
    if any(token in opening for token in (*_TIME_GREETINGS, "晚安", "起床", "问候")):
        return "greeting"
    if value and value not in {"other", "unknown", "none"}:
        return aliases.get(value, value)
    if any(token in text for token in ("提醒", "记得", "别忘")):
        return "reminder"
    if any(token in text for token in ("难过", "辛苦", "安慰", "抱抱")):
        return "comfort"
    if any(token in text for token in ("最近", "怎么样", "还好吗", "关心")):
        return "check_in"
    if any(token in text for token in ("资讯", "新闻", "日报")):
        return "daily_digest"
    return "other"


class OutboundDedupService:
    def __init__(self, storage: Optional[StorageService] = None) -> None:
        self.storage = storage or StorageService()
        self.settings = get_settings()

    def check(
        self,
        *,
        target_type: str,
        target_id: int,
        intent: str,
        content: str,
        now: Optional[datetime] = None,
    ) -> DedupDecision:
        normalized_intent = canonical_intent(intent, content)
        normalized_content = normalize_outbound_text(content)
        if not normalized_content:
            return DedupDecision(False, "empty outbound content")
        records = self.storage.list_recent_outbound_messages(
            target_type,
            target_id,
            hours=max(
                self.settings.outbound_dedup_hours,
                self.settings.outbound_greeting_cooldown_hours,
            ),
            limit=self.settings.outbound_dedup_max_records,
            now=now,
        )
        threshold = min(1.0, max(0.5, self.settings.outbound_dedup_similarity))
        current = now or datetime.now()
        for record in records:
            if canonical_intent(record.intent, record.content) != normalized_intent:
                continue
            age_hours = max(0.0, (current.timestamp() - record.created_at.timestamp()) / 3600)
            if (
                normalized_intent == "greeting"
                and age_hours < self.settings.outbound_greeting_cooldown_hours
            ):
                return DedupDecision(
                    False,
                    "greeting already sent within cooldown",
                    outbound_similarity(content, record.content),
                    record.message_id,
                )
            if age_hours > self.settings.outbound_dedup_hours:
                continue
            similarity = outbound_similarity(content, record.content)
            if similarity >= threshold:
                return DedupDecision(
                    False,
                    f"similar {normalized_intent} message already sent",
                    similarity,
                    record.message_id,
                )
        return DedupDecision(True)

    def record(
        self,
        *,
        target_type: str,
        target_id: int,
        intent: str,
        content: str,
        source: str,
        created_at: Optional[datetime] = None,
    ) -> OutboundMessageRecord:
        record = OutboundMessageRecord(
            message_id=uuid.uuid4().hex[:12],
            target_type=target_type,  # type: ignore[arg-type]
            target_id=target_id,
            intent=canonical_intent(intent, content),
            content=content,
            normalized_content=normalize_outbound_text(content),
            source=source,
            created_at=created_at or datetime.now(),
        )
        return self.storage.record_outbound_message(record)

    def recent_intents(
        self, target_type: str, target_id: int
    ) -> Iterable[tuple[str, str]]:
        for record in self.storage.list_recent_outbound_messages(target_type, target_id):
            yield record.intent, record.content
