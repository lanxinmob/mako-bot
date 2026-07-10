from __future__ import annotations

import json
import unittest

from src.services.storage import StorageService


class FakeRedis:
    def __init__(self, values: dict[str, str]) -> None:
        self.values = values

    def get(self, key: str):
        return self.values.get(key)

    def set(self, key: str, value: str) -> None:
        self.values[key] = value


class StorageHistoryMigrationTest(unittest.TestCase):
    def test_reads_legacy_key_and_writes_namespaced_key(self) -> None:
        history = [{"role": "user", "content": "hello"}]
        service = object.__new__(StorageService)
        service.redis = FakeRedis({"group_42": json.dumps(history)})
        service.settings = type("Settings", (), {"max_history_turns": 50})()

        self.assertEqual(service.get_history("group_42"), history)
        self.assertEqual(
            json.loads(service.redis.values["chat:history:group_42"]),
            history,
        )

    def test_namespaced_history_wins_over_legacy_key(self) -> None:
        service = object.__new__(StorageService)
        service.redis = FakeRedis(
            {
                "group_42": json.dumps([{"content": "old"}]),
                "chat:history:group_42": json.dumps([{"content": "new"}]),
            }
        )
        service.settings = type("Settings", (), {"max_history_turns": 50})()
        self.assertEqual(service.get_history("group_42"), [{"content": "new"}])


if __name__ == "__main__":
    unittest.main()

