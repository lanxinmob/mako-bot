from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from src.core.config import get_settings
from src.models.schemas import (
    AutonomyGoal,
    AutonomyProgressEvent,
    AutonomyTask,
    BotProfile,
    ChatRecord,
    NoteRecord,
    OutboundMessageRecord,
    RelationshipMemory,
    ThoughtTrace,
)
from src.services.redis import get_redis


@dataclass
class MemoryStorage:
    histories: Dict[str, List[dict]] = field(default_factory=dict)
    all_memory: List[str] = field(default_factory=list)
    outbound_messages: Dict[str, List[dict]] = field(default_factory=dict)
    profiles: Dict[str, str] = field(default_factory=dict)
    notes: Dict[int, Dict[str, dict]] = field(default_factory=dict)
    bot_profiles: Dict[str, dict] = field(default_factory=dict)
    thought_traces: Dict[str, dict] = field(default_factory=dict)
    autonomy_goals: Dict[str, dict] = field(default_factory=dict)
    autonomy_tasks: Dict[str, dict] = field(default_factory=dict)
    autonomy_progress_events: Dict[str, dict] = field(default_factory=dict)
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

    def list_global_records(self, limit: int = 100) -> List[ChatRecord]:
        rows: List[str]
        if self.redis:
            rows = self.redis.lrange("all_memory", -limit, -1) if limit > 0 else self.redis.lrange("all_memory", 0, -1)
        else:
            rows = _memory.all_memory[-limit:] if limit > 0 else _memory.all_memory
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

    def record_outbound_message(self, record: OutboundMessageRecord) -> OutboundMessageRecord:
        key = f"outbound:ledger:{record.target_type}:{record.target_id}"
        payload = json.dumps(record.model_dump(mode="json"), ensure_ascii=False)
        max_records = max(20, self.settings.outbound_dedup_max_records)
        if self.redis:
            self.redis.rpush(key, payload)
            self.redis.ltrim(key, -max_records, -1)
            self.redis.expire(key, max(86400, self.settings.outbound_dedup_hours * 7200))
            return record
        rows = _memory.outbound_messages.setdefault(key, [])
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
                for item in _memory.outbound_messages.get(key, [])[-limit:]
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

    def get_profile(self, user_id: int) -> Optional[dict]:
        key = f"user_profile:{user_id}"
        if self.redis:
            raw = self.redis.get(key)
            return self._parse_profile_payload(raw, key=key) if raw else None
        raw = _memory.profiles.get(key)
        return self._parse_profile_payload(raw, key=key) if raw else None

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

    def list_profiles(self) -> List[dict]:
        if self.redis:
            keys = self.redis.keys("user_profile:*")
            rows = [(str(key), self.redis.get(key)) for key in keys]
        else:
            rows = list(_memory.profiles.items())
        profiles: List[dict] = []
        for key, raw in rows:
            if not raw:
                continue
            profile = self._parse_profile_payload(raw, key=key)
            if profile:
                profiles.append(profile)
        profiles.sort(key=lambda x: x.get("last_updated", ""), reverse=True)
        return profiles

    @staticmethod
    def _parse_profile_payload(raw: str, *, key: str = "") -> Optional[dict]:
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = {"profile_text": raw}
        if not isinstance(parsed, dict):
            parsed = {"profile_text": str(parsed)}
        if "user_id" not in parsed and key.startswith("user_profile:"):
            try:
                parsed["user_id"] = int(key.split(":", 1)[1])
            except (IndexError, ValueError):
                pass
        parsed.setdefault("nickname", f"用户 {parsed.get('user_id', '')}".strip())
        parsed.setdefault("profile_text", "")
        parsed.setdefault("last_updated", "")
        return parsed

    def save_bot_profile(self, profile: BotProfile) -> BotProfile:
        profile.updated_at = datetime.now()
        payload = json.dumps(profile.model_dump(mode="json"), ensure_ascii=False)
        if self.redis:
            self.redis.hset("bot_profiles", profile.profile_id, payload)
            self.redis.set(f"bot_profile:{profile.profile_id}", payload)
            return profile
        _memory.bot_profiles[profile.profile_id] = profile.model_dump(mode="json")
        return profile

    def add_bot_profile(
        self,
        name: str,
        *,
        summary: str = "",
        persona: str = "",
        capabilities: Optional[List[str]] = None,
        limitations: Optional[List[str]] = None,
        status: str = "active",
    ) -> BotProfile:
        profile = BotProfile(
            profile_id=uuid.uuid4().hex[:12],
            name=name,
            summary=summary,
            persona=persona,
            capabilities=capabilities or [],
            limitations=limitations or [],
            status=status,  # type: ignore[arg-type]
        )
        return self.save_bot_profile(profile)

    def get_bot_profile(self, profile_id: str) -> Optional[BotProfile]:
        if self.redis:
            raw = self.redis.get(f"bot_profile:{profile_id}") or self.redis.hget("bot_profiles", profile_id)
            if not raw:
                return None
            try:
                return BotProfile.model_validate_json(raw)
            except Exception:
                return None
        data = _memory.bot_profiles.get(profile_id)
        return BotProfile.model_validate(data) if data else None

    def list_bot_profiles(self, *, status: Optional[str] = None, limit: int = 50) -> List[BotProfile]:
        rows: List[str]
        if self.redis:
            rows = self.redis.hvals("bot_profiles")
            for key in self.redis.keys("bot_profile:*"):
                item = self.redis.get(key)
                if item:
                    rows.append(item)
        else:
            rows = [json.dumps(item, ensure_ascii=False) for item in _memory.bot_profiles.values()]
        profiles: List[BotProfile] = []
        seen: set[str] = set()
        for row in rows:
            try:
                profile = BotProfile.model_validate_json(row)
            except Exception:
                continue
            if profile.profile_id in seen:
                continue
            seen.add(profile.profile_id)
            if status and profile.status != status:
                continue
            profiles.append(profile)
        profiles.sort(key=lambda x: x.updated_at, reverse=True)
        return profiles[:limit]

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

    def list_all_notes(self, limit: int = 200) -> List[NoteRecord]:
        notes: List[NoteRecord] = []
        if self.redis:
            for key in self.redis.keys("notes:*"):
                for item in self.redis.hvals(key):
                    try:
                        notes.append(NoteRecord.model_validate_json(item))
                    except Exception:
                        continue
        else:
            for user_notes in _memory.notes.values():
                for item in user_notes.values():
                    try:
                        notes.append(NoteRecord.model_validate(item))
                    except Exception:
                        continue
        notes.sort(key=lambda x: x.updated_at, reverse=True)
        return notes[:limit]

    def list_long_term_memory_points(self, limit: int = 200) -> List[dict]:
        if not self.redis:
            return []
        points: List[dict] = []
        try:
            keys = self.redis.keys(f"{self.settings.vector_prefix}*")
        except Exception:
            return []
        for key in keys[:limit]:
            try:
                text = self.redis.hget(key, "point_text")
            except Exception:
                continue
            if not text:
                continue
            points.append(
                {
                    "id": str(key).removeprefix(self.settings.vector_prefix),
                    "title": "长期记忆",
                    "content": text,
                    "category": "long_term_memory",
                    "source": "vector_store",
                }
            )
        return points

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
        data = _memory.relationship_memories.get(user_id, {}).get(memory_id)
        return RelationshipMemory.model_validate(data) if data else None

    def update_relationship_memory(
        self,
        user_id: int,
        memory_id: str,
        content: str,
    ) -> Optional[RelationshipMemory]:
        memory = self.get_relationship_memory(user_id, memory_id)
        if not memory:
            return None
        memory.content = content.strip()
        memory.updated_at = datetime.now()
        key = f"relationship:{user_id}"
        payload = json.dumps(memory.model_dump(mode="json"), ensure_ascii=False)
        if self.redis:
            self.redis.hset(key, memory_id, payload)
            return memory
        _memory.relationship_memories.setdefault(user_id, {})[memory_id] = memory.model_dump(mode="json")
        return memory

    def delete_relationship_memory(self, user_id: int, memory_id: str) -> bool:
        key = f"relationship:{user_id}"
        if not self.get_relationship_memory(user_id, memory_id):
            return False
        if self.redis:
            deleted = bool(self.redis.hdel(key, memory_id))
            self.redis.zrem("relationship:followups", f"{user_id}:{memory_id}")
            return deleted
        deleted = _memory.relationship_memories.get(user_id, {}).pop(memory_id, None) is not None
        _memory.relationship_followups.pop(memory_id, None)
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

        data = _memory.relationship_memories.get(user_id, {}).get(memory_id)
        if not data:
            return False
        data["status"] = "done"
        data["last_used_at"] = datetime.now().isoformat()
        data["updated_at"] = datetime.now().isoformat()
        _memory.relationship_followups.pop(memory_id, None)
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
            for user_memories in _memory.relationship_memories.values():
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

    def save_thought_trace(self, trace: ThoughtTrace) -> ThoughtTrace:
        payload = json.dumps(trace.model_dump(mode="json"), ensure_ascii=False)
        if self.redis:
            self.redis.hset("thought_traces", trace.trace_id, payload)
            return trace
        _memory.thought_traces[trace.trace_id] = trace.model_dump(mode="json")
        return trace

    def add_thought_trace(
        self,
        summary: str,
        *,
        trace_kind: str = "chat",
        source: str = "",
        trace_type: str = "",
        input_summary: str = "",
        context_summary: str = "",
        retrieved_summary: str = "",
        decision_summary: str = "",
        output_summary: str = "",
        safety_notes: str = "",
        payload: Optional[dict] = None,
        user_id: Optional[int] = None,
        group_id: Optional[int] = None,
        session_id: Optional[str] = None,
        related_goal_id: Optional[str] = None,
        related_task_id: Optional[str] = None,
    ) -> ThoughtTrace:
        trace = ThoughtTrace(
            trace_id=uuid.uuid4().hex[:12],
            trace_kind=self._normalize_trace_kind(trace_kind),  # type: ignore[arg-type]
            source=source,
            trace_type=trace_type,
            summary=summary,
            input_summary=input_summary,
            context_summary=context_summary,
            retrieved_summary=retrieved_summary,
            decision_summary=decision_summary,
            output_summary=output_summary,
            safety_notes=safety_notes,
            payload=payload or {},
            user_id=user_id,
            group_id=group_id,
            session_id=session_id,
            related_goal_id=related_goal_id,
            related_task_id=related_task_id,
        )
        return self.save_thought_trace(trace)

    def append_thought_trace(self, payload: dict) -> ThoughtTrace:
        created_at = self._parse_datetime(payload.get("created_at"))
        trace_kind = self._normalize_trace_kind(str(payload.get("trace_kind") or payload.get("trace_type") or "chat"))
        trace_payload = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
        derived = self._derive_trace_fields(
            source=str(payload.get("source") or ""),
            trace_type=str(payload.get("trace_type") or payload.get("event_type") or ""),
            summary=str(payload.get("summary") or ""),
            payload=trace_payload,
        )
        trace = ThoughtTrace(
            trace_id=str(payload.get("trace_id") or uuid.uuid4().hex[:12]),
            trace_kind=trace_kind,  # type: ignore[arg-type]
            source=str(payload.get("source") or ""),
            trace_type=str(payload.get("trace_type") or payload.get("event_type") or ""),
            summary=str(payload.get("summary") or ""),
            input_summary=str(payload.get("input_summary") or derived["input_summary"]),
            context_summary=str(payload.get("context_summary") or derived["context_summary"]),
            retrieved_summary=str(payload.get("retrieved_summary") or derived["retrieved_summary"]),
            decision_summary=str(payload.get("decision_summary") or derived["decision_summary"]),
            output_summary=str(payload.get("output_summary") or derived["output_summary"]),
            safety_notes=str(payload.get("safety_notes") or derived["safety_notes"]),
            payload=trace_payload,
            user_id=self._optional_int(payload.get("user_id") or trace_payload.get("user_id")),
            group_id=self._optional_int(payload.get("group_id") or trace_payload.get("group_id")),
            session_id=payload.get("session_id"),
            related_goal_id=payload.get("related_goal_id") or payload.get("goal_id"),
            related_task_id=payload.get("related_task_id") or payload.get("task_id"),
            created_at=created_at or datetime.now(),
        )
        return self.save_thought_trace(trace)

    @staticmethod
    def _derive_trace_fields(source: str, trace_type: str, summary: str, payload: dict) -> dict[str, str]:
        def value(key: str, default: str = "") -> str:
            item = payload.get(key, default)
            if item is None:
                return ""
            return str(item)

        source = source or "unknown"
        trace_type = trace_type or "trace"
        base_safety = "仅保存可审计摘要，不保存隐藏推理链。"

        if source == "autonomy" or "decision" in trace_type:
            target_type = value("target_type", "none")
            target_id = value("target_id", "none")
            confidence = value("confidence", "0")
            risk = value("risk", "unknown")
            reason = value("reason", "未提供原因")
            action = value("action", "unknown")
            message_preview = value("message_preview")
            context_preview = value("context_preview")
            target_hint = payload.get("target_hint")
            recent_count = value("recent_record_count", "0")
            return {
                "input_summary": value("suggestion_preview", "定时扫描或 owner 建议触发了一次自主行动判断。"),
                "context_summary": (
                    f"读取 {recent_count} 条近期记录；目标解析提示：{target_hint or '无'}；"
                    f"上下文预览：{context_preview or '未保存上下文预览'}"
                ),
                "retrieved_summary": (
                    "使用 AUTONOMY_GROUP_IDS、AUTONOMY_PRIVATE_USER_IDS、动态白名单、recent global records 和治理规则。"
                    f" 群白名单={payload.get('allowed_groups') or []}；私聊白名单={payload.get('allowed_private_users') or []}。"
                ),
                "decision_summary": (
                    f"action={action}; target={target_type}:{target_id}; "
                    f"confidence={confidence}; risk={risk}; reason={reason}"
                ),
                "output_summary": f"候选输出：{message_preview}" if message_preview else "本次没有形成可发送内容。",
                "safety_notes": (
                    f"{base_safety} 低风险高置信才直接行动；中风险/低置信先问 owner；高风险或疑似越界保持静默。"
                ),
            }

        if source == "chat":
            model = value("model", "unknown")
            return {
                "input_summary": value("input_preview", "收到一条聊天消息。"),
                "context_summary": (
                    f"结合当前会话上下文、用户画像/关系记忆和茉子人格提示生成普通回复；"
                    f"历史轮数={value('history_turns', 'unknown')}。"
                ),
                "retrieved_summary": (
                    f"用户画像摘要：{value('profile_preview', '未保存')}；"
                    f"知识/记忆检索摘要：{value('knowledge_preview', '未保存')}。"
                ),
                "decision_summary": f"生成普通聊天回复；模型={model}；没有触发自主行动发送决策。",
                "output_summary": value("reply_preview", "回复内容未写入摘要。"),
                "safety_notes": base_safety,
            }

        if source == "notes":
            title = value("title", "未命名笔记")
            category = value("category", "default")
            return {
                "input_summary": f"笔记变更：{title}",
                "context_summary": f"用户 {value('user_id', 'unknown')} 的笔记分类为 {category}。",
                "retrieved_summary": "写入 StorageService notes:*，并同步到向量索引用于后续检索。",
                "decision_summary": "这是记忆沉淀事件，不是主动发言决策。",
                "output_summary": value("content_preview", "笔记内容摘要未提供。"),
                "safety_notes": base_safety,
            }

        if source == "relationship":
            memory_count = value("memory_count", "0")
            memory_types = payload.get("memory_types")
            if not memory_types and isinstance(payload.get("memories"), list):
                memory_types = [item.get("memory_type") for item in payload["memories"] if isinstance(item, dict)]
            return {
                "input_summary": f"从用户 {value('user_id', 'unknown')} 的消息中抽取关系记忆。",
                "context_summary": value("text_preview", "关系抽取没有保存原文摘要。"),
                "retrieved_summary": f"抽取到 {memory_count} 条关系记忆；类型：{memory_types or '未标注'}。",
                "decision_summary": "将命中的偏好、禁忌、事件或承诺写入关系记忆与用户档案。",
                "output_summary": "关系记忆已同步到 StorageService、用户档案和笔记/向量索引。",
                "safety_notes": base_safety,
            }

        return {
            "input_summary": summary,
            "context_summary": "旧记录没有保存更细的上下文字段。",
            "retrieved_summary": "旧记录没有保存检索记忆摘要。",
            "decision_summary": "旧记录没有保存结构化决策字段。",
            "output_summary": "旧记录没有保存最终输出摘要。",
            "safety_notes": base_safety,
        }

    def get_thought_trace(self, trace_id: str) -> Optional[ThoughtTrace]:
        if self.redis:
            raw = self.redis.hget("thought_traces", trace_id)
            if not raw:
                return None
            try:
                return ThoughtTrace.model_validate_json(raw)
            except Exception:
                return None
        data = _memory.thought_traces.get(trace_id)
        return ThoughtTrace.model_validate(data) if data else None

    def list_thought_traces(
        self,
        *,
        trace_kind: Optional[str] = None,
        user_id: Optional[int] = None,
        limit: int = 100,
    ) -> List[ThoughtTrace]:
        rows: List[str]
        if self.redis:
            rows = self.redis.hvals("thought_traces")
        else:
            rows = [json.dumps(item, ensure_ascii=False) for item in _memory.thought_traces.values()]
        traces: List[ThoughtTrace] = []
        for row in rows:
            try:
                trace = ThoughtTrace.model_validate_json(row)
            except Exception:
                continue
            if trace_kind and trace.trace_kind != trace_kind:
                continue
            if user_id is not None and trace.user_id != user_id:
                continue
            traces.append(trace)
        traces.sort(key=lambda x: x.created_at, reverse=True)
        return traces[:limit]

    def save_autonomy_goal(self, goal: AutonomyGoal) -> AutonomyGoal:
        goal.updated_at = datetime.now()
        payload = json.dumps(goal.model_dump(mode="json"), ensure_ascii=False)
        if self.redis:
            self.redis.hset("autonomy:goals", goal.goal_id, payload)
            return goal
        _memory.autonomy_goals[goal.goal_id] = goal.model_dump(mode="json")
        return goal

    def add_autonomy_goal(
        self,
        title: str,
        *,
        summary: str = "",
        status: str = "active",
        priority: int = 0,
        owner: str = "bot",
        due_at: Optional[datetime] = None,
    ) -> AutonomyGoal:
        goal = AutonomyGoal(
            goal_id=uuid.uuid4().hex[:12],
            title=title,
            summary=summary,
            status=status,  # type: ignore[arg-type]
            priority=priority,
            owner=owner,
            due_at=due_at,
        )
        return self.save_autonomy_goal(goal)

    def get_autonomy_goal(self, goal_id: str) -> Optional[AutonomyGoal]:
        if self.redis:
            raw = self.redis.hget("autonomy:goals", goal_id)
            if not raw:
                return None
            try:
                return AutonomyGoal.model_validate_json(raw)
            except Exception:
                return None
        data = _memory.autonomy_goals.get(goal_id)
        return AutonomyGoal.model_validate(data) if data else None

    def list_autonomy_goals(self, *, status: Optional[str] = None, limit: int = 100) -> List[AutonomyGoal]:
        rows: List[str]
        if self.redis:
            rows = self.redis.hvals("autonomy:goals")
        else:
            rows = [json.dumps(item, ensure_ascii=False) for item in _memory.autonomy_goals.values()]
        goals: List[AutonomyGoal] = []
        for row in rows:
            try:
                goal = AutonomyGoal.model_validate_json(row)
            except Exception:
                continue
            if status and goal.status != status:
                continue
            goals.append(goal)
        goals.sort(key=lambda x: (x.priority, x.updated_at), reverse=True)
        return goals[:limit]

    def save_autonomy_task(self, task: AutonomyTask) -> AutonomyTask:
        task.updated_at = datetime.now()
        payload = json.dumps(task.model_dump(mode="json"), ensure_ascii=False)
        if self.redis:
            self.redis.hset("autonomy:tasks", task.task_id, payload)
            return task
        _memory.autonomy_tasks[task.task_id] = task.model_dump(mode="json")
        return task

    def add_autonomy_task(
        self,
        title: str,
        *,
        goal_id: Optional[str] = None,
        summary: str = "",
        status: str = "todo",
        priority: int = 0,
        due_at: Optional[datetime] = None,
    ) -> AutonomyTask:
        task = AutonomyTask(
            task_id=uuid.uuid4().hex[:12],
            goal_id=goal_id,
            title=title,
            summary=summary,
            status=status,  # type: ignore[arg-type]
            priority=priority,
            due_at=due_at,
        )
        return self.save_autonomy_task(task)

    def get_autonomy_task(self, task_id: str) -> Optional[AutonomyTask]:
        if self.redis:
            raw = self.redis.hget("autonomy:tasks", task_id)
            if not raw:
                return None
            try:
                return AutonomyTask.model_validate_json(raw)
            except Exception:
                return None
        data = _memory.autonomy_tasks.get(task_id)
        return AutonomyTask.model_validate(data) if data else None

    def list_autonomy_tasks(
        self,
        *,
        goal_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[AutonomyTask]:
        rows: List[str]
        if self.redis:
            rows = self.redis.hvals("autonomy:tasks")
        else:
            rows = [json.dumps(item, ensure_ascii=False) for item in _memory.autonomy_tasks.values()]
        tasks: List[AutonomyTask] = []
        for row in rows:
            try:
                task = AutonomyTask.model_validate_json(row)
            except Exception:
                continue
            if goal_id and task.goal_id != goal_id:
                continue
            if status and task.status != status:
                continue
            tasks.append(task)
        tasks.sort(key=lambda x: (x.priority, x.updated_at), reverse=True)
        return tasks[:limit]

    def save_autonomy_progress_event(self, event: AutonomyProgressEvent) -> AutonomyProgressEvent:
        payload = json.dumps(event.model_dump(mode="json"), ensure_ascii=False)
        if self.redis:
            self.redis.hset("autonomy:progress_events", event.event_id, payload)
            return event
        _memory.autonomy_progress_events[event.event_id] = event.model_dump(mode="json")
        return event

    def get_autonomy_progress_event(self, event_id: str) -> Optional[AutonomyProgressEvent]:
        if self.redis:
            raw = self.redis.hget("autonomy:progress_events", event_id)
            if not raw:
                return None
            try:
                return AutonomyProgressEvent.model_validate_json(raw)
            except Exception:
                return None
        data = _memory.autonomy_progress_events.get(event_id)
        return AutonomyProgressEvent.model_validate(data) if data else None

    def add_autonomy_progress_event(
        self,
        summary: str,
        *,
        event_kind: str = "note",
        source: str = "",
        event_type: str = "",
        payload: Optional[dict] = None,
        goal_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> AutonomyProgressEvent:
        event = AutonomyProgressEvent(
            event_id=uuid.uuid4().hex[:12],
            event_kind=self._normalize_progress_event_kind(event_kind),  # type: ignore[arg-type]
            source=source,
            event_type=event_type,
            summary=summary,
            payload=payload or {},
            goal_id=goal_id,
            task_id=task_id,
        )
        return self.save_autonomy_progress_event(event)

    def append_progress_event(self, payload: dict) -> AutonomyProgressEvent:
        event_type = str(payload.get("event_type") or payload.get("event_kind") or "note")
        event_kind = self._normalize_progress_event_kind(event_type)
        created_at = self._parse_datetime(payload.get("created_at"))
        event = AutonomyProgressEvent(
            event_id=str(payload.get("event_id") or uuid.uuid4().hex[:12]),
            event_kind=event_kind,  # type: ignore[arg-type]
            source=str(payload.get("source") or ""),
            event_type=event_type,
            summary=str(payload.get("summary") or ""),
            payload=payload.get("payload") if isinstance(payload.get("payload"), dict) else {},
            goal_id=payload.get("goal_id"),
            task_id=payload.get("task_id"),
            created_at=created_at or datetime.now(),
        )
        return self.save_autonomy_progress_event(event)

    def list_autonomy_progress_events(
        self,
        *,
        goal_id: Optional[str] = None,
        task_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[AutonomyProgressEvent]:
        rows: List[str]
        if self.redis:
            rows = self.redis.hvals("autonomy:progress_events")
        else:
            rows = [json.dumps(item, ensure_ascii=False) for item in _memory.autonomy_progress_events.values()]
        events: List[AutonomyProgressEvent] = []
        for row in rows:
            try:
                event = AutonomyProgressEvent.model_validate_json(row)
            except Exception:
                continue
            if goal_id and event.goal_id != goal_id:
                continue
            if task_id and event.task_id != task_id:
                continue
            events.append(event)
        events.sort(key=lambda x: x.created_at, reverse=True)
        return events[:limit]

    @staticmethod
    def _parse_datetime(value: object) -> Optional[datetime]:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str) and value:
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None
        return None

    @staticmethod
    def _optional_int(value: object) -> Optional[int]:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalize_progress_event_kind(event_type: str) -> str:
        if event_type in {
            "created",
            "updated",
            "blocked",
            "completed",
            "cancelled",
            "note",
            "decision",
            "sent",
            "ask_owner",
            "rejected",
            "approved",
            "rewritten",
            "silent",
        }:
            return event_type
        if "approve" in event_type or "批准" in event_type:
            return "approved"
        if "cancel" in event_type or "取消" in event_type:
            return "cancelled"
        if "rewrite" in event_type or "改写" in event_type:
            return "rewritten"
        if "ask" in event_type or "owner" in event_type:
            return "ask_owner"
        if "sent" in event_type or "send" in event_type:
            return "sent"
        if "silent" in event_type:
            return "silent"
        if "decision" in event_type:
            return "decision"
        return "note"

    @staticmethod
    def _normalize_trace_kind(trace_type: str) -> str:
        if trace_type in {"chat", "tool", "autonomy", "system"}:
            return trace_type
        if trace_type.startswith("autonomy") or trace_type.startswith("decision"):
            return "autonomy"
        if trace_type.startswith("tool"):
            return "tool"
        return "chat"

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
