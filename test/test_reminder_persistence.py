from __future__ import annotations

from datetime import datetime

from src.models.schemas import ReminderRecord
from src.services.reminder import Reminder, ReminderBook


class FakeReminderStorage:
    def __init__(self) -> None:
        self.items: dict[str, ReminderRecord] = {}

    def save_reminder(self, item: ReminderRecord) -> ReminderRecord:
        self.items[item.reminder_id] = item
        return item

    def get_reminder(self, reminder_id: str):
        return self.items.get(reminder_id)

    def list_reminders(self, session_id=None, *, user_id=None):
        values = list(self.items.values())
        return [
            item
            for item in values
            if (session_id is None or item.session_id == session_id)
            and (user_id is None or item.user_id == user_id)
        ]

    def delete_reminder(self, reminder_id: str) -> bool:
        return self.items.pop(reminder_id, None) is not None


def test_reminder_survives_repository_reconstruction() -> None:
    storage = FakeReminderStorage()
    first = ReminderBook(storage=storage)
    reminder = Reminder(
        "job-1",
        "喝水",
        datetime(2026, 7, 12, 9, 0),
        session_id="group_1",
        user_id=2,
        group_id=1,
    )
    first.add("group_1", reminder)

    reconstructed = ReminderBook(storage=storage)
    assert reconstructed.list("group_1") == [reminder]
    assert reconstructed.find("group_1", "喝水", user_id=2) == reminder
    assert reconstructed.find("group_1", "喝水", user_id=3) is None
    assert reconstructed.remove("group_1", "job-1") == reminder
    assert reconstructed.list_all() == []


def test_group_reminder_listing_is_scoped_to_the_owner() -> None:
    storage = FakeReminderStorage()
    book = ReminderBook(storage=storage)
    first = Reminder("job-1", "喝水", datetime(2026, 7, 12, 9, 0), "group_1", 2, 1)
    second = Reminder("job-2", "开会", datetime(2026, 7, 12, 10, 0), "group_1", 3, 1)
    book.add("group_1", first)
    book.add("group_1", second)

    assert book.list("group_1", user_id=2) == [first]
    assert book.list("group_1", user_id=3) == [second]
