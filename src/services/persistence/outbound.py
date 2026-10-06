from __future__ import annotations

import json
from datetime import datetime
from typing import List, Optional

from src.models.schemas import OutboundMessageRecord


from src.services.persistence.backends import Repository


class OutboundRepository(Repository):
    def record_outbound_message(self, record: OutboundMessageRecord) -> OutboundMessageRecord:
        key = f"outbound:ledger:{record.target_type}:{record.target_id}"
        payload = json.dumps(record.model_dump(mode="json"), ensure_ascii=False)
        max_records = max(20, self.settings.outbound_dedup_max_records)
        if self.redis:
            self.redis.rpush(key, payload)
            self.redis.ltrim(key, -max_records, -1)
            retention_hours = max(
                self.settings.outbound_dedup_hours,
                self.settings.outbound_greeting_cooldown_hours,
            )
            self.redis.expire(key, max(86400, retention_hours * 7200))
            return record
        rows = self.backend.memory.outbound_messages.setdefault(key, [])
        rows.append(record.model_dump(mode="json"))
        del rows[:-max_records]
        return record

    def list_recent_outbound_messages(
        self,
        target_type: str,
        target_id: int,
        *,
        hours: Optional[int] = None,
        limit: Optional[int] = None,
        now: Optional[datetime] = None,
    ) -> List[OutboundMessageRecord]:
        key = f"outbound:ledger:{target_type}:{target_id}"
        limit = max(1, limit or self.settings.outbound_dedup_max_records)
        if self.redis:
            rows = self.redis.lrange(key, -limit, -1)
        else:
            rows = [
                json.dumps(item, ensure_ascii=False)
                for item in self.backend.memory.outbound_messages.get(key, [])[-limit:]
            ]
        current = now or datetime.now()
        threshold = current.timestamp() - max(1, hours or self.settings.outbound_dedup_hours) * 3600
        records: List[OutboundMessageRecord] = []
        for row in rows:
            try:
                record = OutboundMessageRecord.model_validate_json(row)
            except Exception:
                continue
            if record.created_at.timestamp() >= threshold:
                records.append(record)
        records.sort(key=lambda item: item.created_at, reverse=True)
        return records

    def list_sent_news(self) -> set[str]:
        if self.redis:
            return {str(item) for item in self.redis.hkeys("news:sent")}
        return set(self.backend.memory.sent_news)

    def record_sent_news(self, fingerprints: List[str], *, sent_at: Optional[datetime] = None) -> None:
        values = {item for item in fingerprints if item}
        if not values:
            return
        timestamp = (sent_at or datetime.now()).timestamp()
        if self.redis:
            self.redis.hset("news:sent", mapping={item: timestamp for item in values})
            return
        self.backend.memory.sent_news.update({item: timestamp for item in values})
