from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import List, Optional

from src.models.schemas import RelationshipMemory


from src.services.persistence.backends import Repository
from .followups import mutate


class RelationshipsRepository(Repository):
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
            if not mutate(self.redis, "create", user_id, memory.memory_id, payload=payload,
                          revision=uuid.uuid4().hex, due=due_at.timestamp() if due_at else ""):
                raise RuntimeError("relationship memory id already exists")
            return memory

        self.backend.memory.relationship_memories.setdefault(user_id, {})[memory.memory_id] = memory.model_dump(mode="json")
        if due_at:
            self.backend.memory.relationship_followups[memory.memory_id] = (user_id, due_at.timestamp())
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
                for item in self.backend.memory.relationship_memories.get(user_id, {}).values()
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

    def get_relationship_memory(self, user_id: int, memory_id: str) -> Optional[RelationshipMemory]:
        key = f"relationship:{user_id}"
        if self.redis:
            raw = self.redis.hget(key, memory_id)
            if not raw:
                return None
            try:
                return RelationshipMemory.model_validate_json(raw)
            except Exception:
                return None
        data = self.backend.memory.relationship_memories.get(user_id, {}).get(memory_id)
        return RelationshipMemory.model_validate(data) if data else None

    def update_relationship_memory(
        self,
        user_id: int,
        memory_id: str,
        content: str,
    ) -> Optional[RelationshipMemory]:
        client = self.redis
        raw = client.hget(f"relationship:{user_id}", memory_id) if client else None
        if client:
            try:
                memory = RelationshipMemory.model_validate_json(raw) if raw else None
            except Exception:
                return None
        else:
            memory = self.get_relationship_memory(user_id, memory_id)
        if not memory:
            return None
        memory.content = content.strip()
        memory.updated_at = datetime.now()
        key = f"relationship:{user_id}"
        payload = json.dumps(memory.model_dump(mode="json"), ensure_ascii=False)
        if client:
            return memory if mutate(client, "update", user_id, memory_id, expected=raw,
                                    payload=payload, revision=uuid.uuid4().hex) else None
        self.backend.memory.relationship_memories.setdefault(user_id, {})[memory_id] = memory.model_dump(mode="json")
        return memory

    def delete_relationship_memory(self, user_id: int, memory_id: str) -> bool:
        key = f"relationship:{user_id}"
        client = self.redis
        if client:
            raw = client.hget(key, memory_id)
            return bool(raw and mutate(client, "delete", user_id, memory_id, expected=raw))
        if not self.get_relationship_memory(user_id, memory_id):
            return False
        deleted = self.backend.memory.relationship_memories.get(user_id, {}).pop(memory_id, None) is not None
        self.backend.memory.relationship_followups.pop(memory_id, None)
        return deleted

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
            mem.updated_at = datetime.now()
            self.redis.hset(key, memory_id, json.dumps(mem.model_dump(mode="json"), ensure_ascii=False))
            self.redis.zrem("relationship:followups", f"{user_id}:{memory_id}")
            return True

        data = self.backend.memory.relationship_memories.get(user_id, {}).get(memory_id)
        if not data:
            return False
        data["status"] = "done"
        data["last_used_at"] = datetime.now().isoformat()
        data["updated_at"] = datetime.now().isoformat()
        self.backend.memory.relationship_followups.pop(memory_id, None)
        return True

    def list_all_relationship_memories(
        self,
        *,
        memory_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 200,
    ) -> List[RelationshipMemory]:
        rows: List[str] = []
        if self.redis:
            for key in self.redis.keys("relationship:*"):
                if key == "relationship:followups":
                    continue
                rows.extend(self.redis.hvals(key))
        else:
            for user_memories in self.backend.memory.relationship_memories.values():
                rows.extend(json.dumps(item, ensure_ascii=False) for item in user_memories.values())

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
        for memory_id, (user_id, ts) in list(self.backend.memory.relationship_followups.items()):
            if ts > now.timestamp():
                continue
            payload = self.backend.memory.relationship_memories.get(user_id, {}).get(memory_id)
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
