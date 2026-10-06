from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import List, Optional

from src.models.schemas import AutonomyGoal


from src.services.persistence.backends import Repository


class GoalsRepository(Repository):
    def save_autonomy_goal(self, goal: AutonomyGoal) -> AutonomyGoal:
        goal.updated_at = datetime.now()
        payload = json.dumps(goal.model_dump(mode="json"), ensure_ascii=False)
        if self.redis:
            self.redis.hset("autonomy:goals", goal.goal_id, payload)
            return goal
        self.backend.memory.autonomy_goals[goal.goal_id] = goal.model_dump(mode="json")
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
        data = self.backend.memory.autonomy_goals.get(goal_id)
        return AutonomyGoal.model_validate(data) if data else None

    def list_autonomy_goals(self, *, status: Optional[str] = None, limit: int = 100) -> List[AutonomyGoal]:
        rows: List[str]
        if self.redis:
            rows = self.redis.hvals("autonomy:goals")
        else:
            rows = [json.dumps(item, ensure_ascii=False) for item in self.backend.memory.autonomy_goals.values()]
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
