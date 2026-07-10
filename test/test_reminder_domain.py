from __future__ import annotations

import unittest
from datetime import datetime

from src.services.reminder import Reminder, ReminderBook, extract_json_object, generate_job_id


class ReminderJsonTest(unittest.TestCase):
    def test_extracts_fenced_json(self) -> None:
        self.assertEqual(
            extract_json_object('```json\n{"intent":"NONE"}\n```'),
            {"intent": "NONE"},
        )

    def test_rejects_non_object_json(self) -> None:
        self.assertIsNone(extract_json_object('["NONE"]'))


class ReminderBookTest(unittest.TestCase):
    def setUp(self) -> None:
        self.book = ReminderBook()
        self.when = datetime(2026, 7, 10, 20, 0)
        self.reminder = Reminder("job-1", "喝水", self.when)

    def test_add_find_remove_lifecycle(self) -> None:
        self.book.add("group_1", self.reminder)
        self.assertEqual(self.book.find("group_1", "喝"), self.reminder)
        self.assertEqual(self.book.remove("group_1", "job-1"), self.reminder)
        self.assertEqual(self.book.list("group_1"), [])

    def test_list_returns_copy(self) -> None:
        self.book.add("group_1", self.reminder)
        snapshot = self.book.list("group_1")
        snapshot.clear()
        self.assertEqual(self.book.list("group_1"), [self.reminder])

    def test_job_id_is_stable_and_scoped(self) -> None:
        first = generate_job_id(1, 2, self.when)
        self.assertEqual(first, generate_job_id(1, 2, self.when))
        self.assertNotEqual(first, generate_job_id(1, 3, self.when))


if __name__ == "__main__":
    unittest.main()

