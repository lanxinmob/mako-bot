from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import List, Optional

from src.models.schemas import AutonomyTask


from src.services.persistence.backends import Repository


class TasksRepository(Repository):
    def save_autonomy_task(self, task: AutonomyTask) -> AutonomyTask:
        task.updated_at = datetime.now()
        payload = json.dumps(task.model_dump(mode="json"), ensure_ascii=False)
        if self.redis:
            self.redis.hset("autonomy:tasks", task.task_id, payload)
            return task
        self.backend.memory.autonomy_tasks[task.task_id] = task.model_dump(mode="json")
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
        data = self.backend.memory.autonomy_tasks.get(task_id)
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
            rows = [json.dumps(item, ensure_ascii=False) for item in self.backend.memory.autonomy_tasks.values()]
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
