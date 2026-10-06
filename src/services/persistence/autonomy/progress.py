from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import List, Optional

from src.models.schemas import AutonomyProgressEvent


from src.services.persistence.backends import Repository
from src.services.persistence.autonomy import normalization


class ProgressRepository(Repository):
    def save_autonomy_progress_event(self, event: AutonomyProgressEvent) -> AutonomyProgressEvent:
        payload = json.dumps(event.model_dump(mode="json"), ensure_ascii=False)
        if self.redis:
            self.redis.hset("autonomy:progress_events", event.event_id, payload)
            return event
        self.backend.memory.autonomy_progress_events[event.event_id] = event.model_dump(mode="json")
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
        data = self.backend.memory.autonomy_progress_events.get(event_id)
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
            event_kind=normalization.normalize_progress_event_kind(event_kind),  # type: ignore[arg-type]
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
        event_kind = normalization.normalize_progress_event_kind(event_type)
        created_at = normalization.parse_datetime(payload.get("created_at"))
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
            rows = [json.dumps(item, ensure_ascii=False) for item in self.backend.memory.autonomy_progress_events.values()]
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
