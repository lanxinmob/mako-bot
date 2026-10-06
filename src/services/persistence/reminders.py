from __future__ import annotations

import json
from typing import List, Optional

from src.models.schemas import ReminderRecord


from src.services.persistence.backends import Repository


class RemindersRepository(Repository):
    def save_reminder(self, reminder: ReminderRecord) -> ReminderRecord:
        payload = json.dumps(reminder.model_dump(mode="json"), ensure_ascii=False)
        if self.redis:
            self.redis.hset("reminders", reminder.reminder_id, payload)
            return reminder
        self.backend.memory.reminders[reminder.reminder_id] = reminder.model_dump(mode="json")
        return reminder

    def get_reminder(self, reminder_id: str) -> Optional[ReminderRecord]:
        if self.redis:
            raw = self.redis.hget("reminders", reminder_id)
            return ReminderRecord.model_validate_json(raw) if raw else None
        payload = self.backend.memory.reminders.get(reminder_id)
        return ReminderRecord.model_validate(payload) if payload else None

    def list_reminders(
        self,
        session_id: Optional[str] = None,
        *,
        user_id: Optional[int] = None,
    ) -> List[ReminderRecord]:
        if self.redis:
            reminders: List[ReminderRecord] = []
            for row in self.redis.hvals("reminders"):
                try:
                    reminders.append(ReminderRecord.model_validate_json(row))
                except Exception:
                    continue
        else:
            reminders = [
                ReminderRecord.model_validate(item) for item in self.backend.memory.reminders.values()
            ]
        if session_id is not None:
            reminders = [item for item in reminders if item.session_id == session_id]
        if user_id is not None:
            reminders = [item for item in reminders if item.user_id == user_id]
        reminders.sort(key=lambda item: item.remind_time)
        return reminders

    def delete_reminder(self, reminder_id: str) -> bool:
        if self.redis:
            return bool(self.redis.hdel("reminders", reminder_id))
        return self.backend.memory.reminders.pop(reminder_id, None) is not None
