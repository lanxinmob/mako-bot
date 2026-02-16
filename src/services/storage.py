from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from src.core.config import get_settings
from src.models.schemas import ChatRecord, NoteRecord, RelationshipMemory
from src.services.redis import get_redis


@dataclass
class MemoryStorage:
    histories: Dict[str, List[dict]] = field(default_factory=dict)
    all_memory: List[str] = field(default_factory=list)
    profiles: Dict[str, str] = field(default_factory=dict)
    notes: Dict[int, Dict[str, dict]] = field(default_factory=dict)
    affinity: Dict[int, int] = field(default_factory=dict)
    affinity_daily: Dict[str, int] = field(default_factory=dict)
    relationship_memories: Dict[int, Dict[str, dict]] = field(default_factory=dict)
    relationship_followups: Dict[str, tuple[int, float]] = field(default_factory=dict)
    blacklisted_users: Dict[int, str] = field(default_factory=dict)
    blacklisted_groups: Dict[int, str] = field(default_factory=dict)
    daily_costs: Dict[str, float] = field(default_factory=dict)


_memory = MemoryStorage()


class StorageService:
    def __init__(self) -> None:
        self.redis = get_redis()
        self.settings = get_settings()

    def get_history(self, session_id: str) -> List[dict]:
        if self.redis:
            raw = self.redis.get(f"chat:history:{session_id}")
            if raw:
                try:
                    return json.loads(raw)
                except Exception:
                    return []
            return []
        return _memory.histories.get(session_id, [])

    def save_history(self, session_id: str, messages: List[dict]) -> None:
        max_items = self.settings.max_history_turns * 2
        clipped = messages[-max_items:]
        if self.redis:
            self.redis.set(f"chat:history:{session_id}", json.dumps(clipped, ensure_ascii=False))
            return
        _memory.histories[session_id] = clipped

    def append_global_record(self, record: ChatRecord) -> None:
        payload = json.dumps(record.model_dump(mode="json"), ensure_ascii=False)
        if self.redis:
            self.redis.rpush("all_memory", payload)
            return
        _memory.all_memory.append(payload)

    def get_recent_global_records(self, hours: int = 24) -> List[ChatRecord]:
        threshold = datetime.now().timestamp() - hours * 3600
        rows: List[str]
        if self.redis:
            rows = self.redis.lrange("all_memory", 0, -1)
        else:
            rows = _memory.all_memory
        records: List[ChatRecord] = []
        for item in rows:
            try:
                record = ChatRecord.model_validate_json(item)
            except Exception:
                continue
            if record.time.timestamp() >= threshold:
                records.append(record)
        return records

    def get_profile(self, user_id: int) -> Optional[dict]:
        key = f"user_profile:{user_id}"
        if self.redis:
            raw = self.redis.get(key)
            return json.loads(raw) if raw else None
        raw = _memory.profiles.get(key)
        return json.loads(raw) if raw else None

    def set_profile(self, user_id: int, nickname: str, profile_text: str) -> None:
        key = f"user_profile:{user_id}"
        value = {
            "user_id": user_id,
            "nickname": nickname,
            "profile_text": profile_text,
            "last_updated": datetime.now().isoformat(),
        }
        raw = json.dumps(value, ensure_ascii=False)
        if self.redis:
            self.redis.set(key, raw)
            return
        _memory.profiles[key] = raw

    def get_affinity(self, user_id: int) -> int:
        initial = self.settings.affinity_initial
        key = f"affinity:{user_id}"
        if self.redis:
            value = self.redis.get(key)
            return int(value) if value is not None else initial
        return _memory.affinity.get(user_id, initial)

    def adjust_affinity(self, user_id: int, delta: int) -> int:
        min_score = self.settings.affinity_min
        max_score = self.settings.affinity_max
        daily_cap = self.settings.affinity_daily_cap
        day_key = f"{user_id}:{datetime.now().strftime('%Y%m%d')}"

        if self.redis:
            consumed = int(self.redis.get(f"affinity:daily:{day_key}") or 0)
            remain = max(0, daily_cap - consumed)
            effective = max(-remain, min(remain, delta))
            score = self.get_affinity(user_id)
            new_score = max(min_score, min(max_score, score + effective))
            self.redis.set(f"affinity:{user_id}", new_score)
            self.redis.set(f"affinity:daily:{day_key}", consumed + abs(effective), ex=172800)
            return new_score

        consumed = _memory.affinity_daily.get(day_key, 0)
        remain = max(0, daily_cap - consumed)
        effective = max(-remain, min(remain, delta))
        score = self.get_affinity(user_id)
        new_score = max(min_score, min(max_score, score + effective))
        _memory.affinity[user_id] = new_score
        _memory.affinity_daily[day_key] = consumed + abs(effective)
        return new_score

    def add_note(
        self,
        user_id: int,
        title: str,
        content: str,
        category: str = "default",
        visibility: str = "private",
    ) -> NoteRecord:
        note = NoteRecord(
            note_id=uuid.uuid4().hex[:10],
            user_id=user_id,
            title=title,
            content=content,
            category=category,
            visibility=visibility,  # type: ignore[arg-type]
        )
        key = f"notes:{user_id}"
        if self.redis:
            self.redis.hset(key, note.note_id, json.dumps(note.model_dump(mode="json"), ensure_ascii=False))
            return note
        _memory.notes.setdefault(user_id, {})[note.note_id] = note.model_dump(mode="json")
        return note

    def list_notes(self, user_id: int) -> List[NoteRecord]:
        if self.redis:
            raw = self.redis.hvals(f"notes:{user_id}")
            result: List[NoteRecord] = []
            for item in raw:
                try:
                    result.append(NoteRecord.model_validate_json(item))
                except Exception:
                    continue
            result.sort(key=lambda x: x.updated_at, reverse=True)
            return result
        data = _memory.notes.get(user_id, {})
        notes = [NoteRecord.model_validate(item) for item in data.values()]
        notes.sort(key=lambda x: x.updated_at, reverse=True)
        return notes

    def search_notes(self, user_id: int, keyword: str) -> List[NoteRecord]:
        notes = self.list_notes(user_id)
        keyword_lower = keyword.lower()
        return [
            n for n in notes if keyword_lower in n.title.lower() or keyword_lower in n.content.lower()
        ]

    def delete_note(self, user_id: int, note_id_or_keyword: str) -> bool:
        key = f"notes:{user_id}"
        target_id = note_id_or_keyword

        if not target_id:
            return False
        notes = self.list_notes(user_id)
        if target_id not in {n.note_id for n in notes}:
            for note in notes:
                if target_id in note.title or target_id in note.content:
                    target_id = note.note_id
                    break

        if self.redis:
            return bool(self.redis.hdel(key, target_id))
        user_notes = _memory.notes.get(user_id, {})
        return user_notes.pop(target_id, None) is not None

    def update_note(self, user_id: int, note_id_or_keyword: str, new_content: str) -> Optional[NoteRecord]:
        notes = self.list_notes(user_id)
        target: Optional[NoteRecord] = None
        for note in notes:
            if note.note_id == note_id_or_keyword or note_id_or_keyword in note.title:
                target = note
                break
        if not target:
            return None
        target.content = new_content
        target.updated_at = datetime.now()
        key = f"notes:{user_id}"
        if self.redis:
            self.redis.hset(
                key,
                target.note_id,
                json.dumps(target.model_dump(mode="json"), ensure_ascii=False),
            )
            return target
        _memory.notes.setdefault(user_id, {})[target.note_id] = target.model_dump(mode="json")
        return target

    def add_relationship_memory(
        self,
        user_id: int,
        memory_type: str,
        content: str,
        *,
        source: str = "chat",
        confidence: float = 0.8,
        due_at: Optional[datetime] = None,
    ) -> RelationshipMemory:
        memory = RelationshipMemory(
            memory_id=uuid.uuid4().hex[:12],
            user_id=user_id,
            memory_type=memory_type,  # type: ignore[arg-type]
            content=content,
            source=source,
            confidence=confidence,
            due_at=due_at,
        )
        key = f"relationship:{user_id}"
        payload = json.dumps(memory.model_dump(mode="json"), ensure_ascii=False)
        if self.redis:
            self.redis.hset(key, memory.memory_id, payload)
            if due_at:
                self.redis.zadd("relationship:followups", {f"{user_id}:{memory.memory_id}": due_at.timestamp()})
            return memory

        _memory.relationship_memories.setdefault(user_id, {})[memory.memory_id] = memory.model_dump(mode="json")
        if due_at:
            _memory.relationship_followups[memory.memory_id] = (user_id, due_at.timestamp())
        return memory

    def list_relationship_memories(
        self,
        user_id: int,
        *,
        memory_type: Optional[str] = None,
        status: str = "active",
        limit: int = 20,
    ) -> List[RelationshipMemory]:
        rows: List[str]
        if self.redis:
            rows = self.redis.hvals(f"relationship:{user_id}")
        else:
            rows = [
                json.dumps(item, ensure_ascii=False)
                for item in _memory.relationship_memories.get(user_id, {}).values()
            ]
        memories: List[RelationshipMemory] = []
        for row in rows:
            try:
                mem = RelationshipMemory.model_validate_json(row)
            except Exception:
                continue
            if memory_type and mem.memory_type != memory_type:
                continue
            if status and mem.status != status:
                continue
            memories.append(mem)
        memories.sort(key=lambda x: x.created_at, reverse=True)
        return memories[:limit]

    def mark_relationship_done(self, user_id: int, memory_id: str) -> bool:
        key = f"relationship:{user_id}"
        if self.redis:
            raw = self.redis.hget(key, memory_id)
            if not raw:
                return False
            try:
                mem = RelationshipMemory.model_validate_json(raw)
            except Exception:
                return False
            mem.status = "done"
            mem.last_used_at = datetime.now()
            self.redis.hset(key, memory_id, json.dumps(mem.model_dump(mode="json"), ensure_ascii=False))
            self.redis.zrem("relationship:followups", f"{user_id}:{memory_id}")
            return True

        data = _memory.relationship_memories.get(user_id, {}).get(memory_id)
        if not data:
            return False
        data["status"] = "done"
        data["last_used_at"] = datetime.now().isoformat()
        _memory.relationship_followups.pop(memory_id, None)
        return True

    def list_due_followups(self, now: Optional[datetime] = None, limit: int = 20) -> List[RelationshipMemory]:
        now = now or datetime.now()
        if self.redis:
            ids = self.redis.zrangebyscore("relationship:followups", 0, now.timestamp(), start=0, num=limit)
            result: List[RelationshipMemory] = []
            for item in ids:
                parts = item.split(":", 1)
                if len(parts) != 2:
                    continue
                try:
                    user_id = int(parts[0])
                except ValueError:
                    continue
                memory_id = parts[1]
                raw = self.redis.hget(f"relationship:{user_id}", memory_id)
                if not raw:
                    continue
                try:
                    mem = RelationshipMemory.model_validate_json(raw)
                except Exception:
                    continue
                if mem.status == "active":
                    result.append(mem)
            return result

        result: List[RelationshipMemory] = []
        for memory_id, (user_id, ts) in list(_memory.relationship_followups.items()):
            if ts > now.timestamp():
                continue
            payload = _memory.relationship_memories.get(user_id, {}).get(memory_id)
            if not payload:
                continue
            try:
                mem = RelationshipMemory.model_validate(payload)
            except Exception:
                continue
            if mem.status == "active":
                result.append(mem)
        result.sort(key=lambda x: x.created_at)
        return result[:limit]

    def is_user_blacklisted(self, user_id: int) -> bool:
        if self.redis:
            return bool(self.redis.sismember("blacklist:users", user_id))
        return user_id in _memory.blacklisted_users

    def is_group_blacklisted(self, group_id: int) -> bool:
        if self.redis:
            return bool(self.redis.sismember("blacklist:groups", group_id))
        return group_id in _memory.blacklisted_groups

    def add_user_blacklist(self, user_id: int, reason: str = "") -> None:
        if self.redis:
            self.redis.sadd("blacklist:users", user_id)
            if reason:
                self.redis.hset("blacklist:user:reason", user_id, reason)
            return
        _memory.blacklisted_users[user_id] = reason

    def remove_user_blacklist(self, user_id: int) -> None:
        if self.redis:
            self.redis.srem("blacklist:users", user_id)
            self.redis.hdel("blacklist:user:reason", user_id)
            return
        _memory.blacklisted_users.pop(user_id, None)

    def add_group_blacklist(self, group_id: int, reason: str = "") -> None:
        if self.redis:
            self.redis.sadd("blacklist:groups", group_id)
            if reason:
                self.redis.hset("blacklist:group:reason", group_id, reason)
            return
        _memory.blacklisted_groups[group_id] = reason

    def remove_group_blacklist(self, group_id: int) -> None:
        if self.redis:
            self.redis.srem("blacklist:groups", group_id)
            self.redis.hdel("blacklist:group:reason", group_id)
            return
        _memory.blacklisted_groups.pop(group_id, None)

    def consume_cost(self, user_id: int, amount: float, *, at: Optional[datetime] = None) -> None:
        if amount <= 0:
            return
        at = at or datetime.now()
        day = at.strftime("%Y%m%d")
        g_key = f"cost:global:{day}"
        u_key = f"cost:user:{user_id}:{day}"
        if self.redis:
            self.redis.incrbyfloat(g_key, amount)
            self.redis.incrbyfloat(u_key, amount)
            self.redis.expire(g_key, 172800)
            self.redis.expire(u_key, 172800)
            return
        _memory.daily_costs[g_key] = _memory.daily_costs.get(g_key, 0.0) + amount
        _memory.daily_costs[u_key] = _memory.daily_costs.get(u_key, 0.0) + amount

    def get_daily_cost(self, user_id: Optional[int] = None, *, at: Optional[datetime] = None) -> float:
        at = at or datetime.now()
        day = at.strftime("%Y%m%d")
        key = f"cost:global:{day}" if user_id is None else f"cost:user:{user_id}:{day}"
        if self.redis:
            value = self.redis.get(key)
            return float(value) if value is not None else 0.0
        return float(_memory.daily_costs.get(key, 0.0))
