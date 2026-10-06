from __future__ import annotations

import json
from datetime import datetime
from typing import List

from src.models.schemas import ChatRecord


from src.services.persistence.backends import Repository


class HistoryRepository(Repository):
    def get_history(self, session_id: str) -> List[dict]:
        if self.redis:
            raw = self.redis.get(f"chat:history:{session_id}")
            if not raw:
                # Compatibility with the original chat.py, which stored
                # histories under the unprefixed session id.  Migrate on read
                # so deploying the refactor does not reset active chats.
                raw = self.redis.get(session_id)
                if raw:
                    try:
                        history = json.loads(raw)
                    except Exception:
                        return []
                    self.save_history(session_id, history)
                    return history
            if raw:
                try:
                    return json.loads(raw)
                except Exception:
                    return []
            return []
        return self.backend.memory.histories.get(session_id, [])

    def save_history(self, session_id: str, messages: List[dict]) -> None:
        max_items = self.settings.max_history_turns * 2
        clipped = messages[-max_items:]
        if self.redis:
            self.redis.set(f"chat:history:{session_id}", json.dumps(clipped, ensure_ascii=False))
            return
        self.backend.memory.histories[session_id] = clipped

    def append_global_record(self, record: ChatRecord) -> None:
        payload = json.dumps(record.model_dump(mode="json"), ensure_ascii=False)
        if self.redis:
            self.redis.rpush("all_memory", payload)
            self.redis.ltrim(
                "all_memory",
                -max(1000, self.settings.global_memory_max_records),
                -1,
            )
            return
        self.backend.memory.all_memory.append(payload)
        del self.backend.memory.all_memory[:-max(1000, self.settings.global_memory_max_records)]

    def list_global_records(self, limit: int = 100) -> List[ChatRecord]:
        rows: List[str]
        if self.redis:
            rows = self.redis.lrange("all_memory", -limit, -1) if limit > 0 else self.redis.lrange("all_memory", 0, -1)
        else:
            rows = self.backend.memory.all_memory[-limit:] if limit > 0 else self.backend.memory.all_memory
        records: List[ChatRecord] = []
        for item in rows:
            try:
                records.append(ChatRecord.model_validate_json(item))
            except Exception:
                continue
        records.sort(key=lambda x: x.time, reverse=True)
        return records

    def get_recent_global_records(self, hours: int = 24) -> List[ChatRecord]:
        threshold = datetime.now().timestamp() - hours * 3600
        rows: List[str]
        if self.redis:
            rows = self.redis.lrange("all_memory", 0, -1)
        else:
            rows = self.backend.memory.all_memory
        records: List[ChatRecord] = []
        for item in rows:
            try:
                record = ChatRecord.model_validate_json(item)
            except Exception:
                continue
            if record.time.timestamp() >= threshold:
                records.append(record)
        return records
