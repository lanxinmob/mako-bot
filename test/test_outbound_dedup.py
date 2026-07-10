from __future__ import annotations

from datetime import datetime, timedelta

from src.models.schemas import OutboundMessageRecord
from src.services.outbound_dedup import (
    OutboundDedupService,
    canonical_intent,
    outbound_similarity,
)


class FakeLedgerStorage:
    def __init__(self) -> None:
        self.records: list[OutboundMessageRecord] = []

    def record_outbound_message(self, record: OutboundMessageRecord) -> OutboundMessageRecord:
        self.records.append(record)
        return record

    def list_recent_outbound_messages(
        self,
        target_type: str,
        target_id: int,
        *,
        hours: int,
        limit: int,
        now: datetime | None = None,
    ) -> list[OutboundMessageRecord]:
        current = now or datetime.now()
        threshold = current - timedelta(hours=hours)
        return [
            record
            for record in self.records[-limit:]
            if record.target_type == target_type
            and record.target_id == target_id
            and record.created_at >= threshold
        ]


def test_similarity_ignores_persona_fillers_and_punctuation() -> None:
    score = outbound_similarity(
        "茉子大人来报到啦，大家早上好！今天也要元气满满哦~",
        "各位早上好，今天也要元气满满呀。",
    )
    assert score >= 0.82


def test_same_target_and_intent_rejects_similar_message() -> None:
    storage = FakeLedgerStorage()
    service = OutboundDedupService(storage)  # type: ignore[arg-type]
    service.record(
        target_type="group",
        target_id=42,
        intent="greeting",
        content="各位早上好，今天也要元气满满呀。",
        source="test",
    )

    decision = service.check(
        target_type="group",
        target_id=42,
        intent="daily_greeting",
        content="茉子大人来报到啦，大家早上好！今天也要元气满满哦~",
    )

    assert decision.allowed is False
    assert decision.matched_message_id
    assert decision.similarity >= 0.82


def test_different_target_or_intent_is_not_blocked() -> None:
    storage = FakeLedgerStorage()
    service = OutboundDedupService(storage)  # type: ignore[arg-type]
    service.record(
        target_type="group",
        target_id=42,
        intent="greeting",
        content="早上好，今天也加油。",
        source="test",
    )

    assert service.check(
        target_type="group",
        target_id=43,
        intent="greeting",
        content="早上好，今天也加油。",
    ).allowed
    assert service.check(
        target_type="group",
        target_id=42,
        intent="topic_share",
        content="早上好，今天也加油。",
    ).allowed


def test_old_message_outside_window_is_allowed() -> None:
    storage = FakeLedgerStorage()
    storage.records.append(
        OutboundMessageRecord(
            message_id="old",
            target_type="private",
            target_id=7,
            intent="check_in",
            content="最近还好吗？",
            created_at=datetime.now() - timedelta(hours=19),
        )
    )
    service = OutboundDedupService(storage)  # type: ignore[arg-type]

    assert service.check(
        target_type="private",
        target_id=7,
        intent="check_in",
        content="最近还好吗？",
    ).allowed


def test_intent_aliases_are_canonicalized() -> None:
    assert canonical_intent("daily_greeting") == "greeting"
    assert canonical_intent("", "记得按时吃饭") == "reminder"
