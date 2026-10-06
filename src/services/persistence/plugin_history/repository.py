"""Bounded Redis history with an immediate, scoped memory mirror."""
import json
import logging
import re
from threading import RLock

from src.services.persistence.backends import Repository


logger = logging.getLogger(__name__)
LIMIT = 20
MAX_TEXT = 4096
MAX_SESSIONS = 256
_lock = RLock()
_APPEND = """
local rows = redis.call('LRANGE', KEYS[1], 0, -1)
local incoming = cjson.decode(ARGV[1])
local decoded = {}
for _, raw in ipairs(rows) do
    local row = cjson.decode(raw)
    if row.message_id == incoming.message_id then return 0 end
    table.insert(decoded, row)
end
table.insert(decoded, incoming)
table.sort(decoded, function(a, b)
    if a.sent_at_ms == b.sent_at_ms then return a.message_id < b.message_id end
    return a.sent_at_ms < b.sent_at_ms
end)
local result = {}
for i = math.max(1, #decoded - tonumber(ARGV[2]) + 1), #decoded do
    table.insert(result, cjson.encode(decoded[i]))
end
redis.call('DEL', KEYS[1])
redis.call('RPUSH', KEYS[1], unpack(result))
return 1
"""


def valid_entry(entry):
    return (isinstance(entry, dict) and entry.get("role") == "assistant"
            and isinstance(entry.get("content"), str) and 0 < len(entry["content"]) <= MAX_TEXT
            and isinstance(entry.get("message_id"), str)
            and bool(re.fullmatch(r"[A-Za-z0-9_-]{1,100}", entry["message_id"]))
            and type(entry.get("sent_at_ms")) is int and 0 < entry["sent_at_ms"] < 10**14
            and entry.get("category") in {"command", "autonomous", "news", "reminder", "notice"})


def merge_entries(rows):
    unique = {}
    for row in rows:
        if valid_entry(row):
            unique.setdefault(row["message_id"], dict(row))
    return sorted(unique.values(), key=lambda row: (row["sent_at_ms"], row["message_id"]))[-LIMIT:]


class PluginHistoryRepository(Repository):
    @staticmethod
    def key(bot_id, session_id):
        if (not isinstance(bot_id, str) or not re.fullmatch(r"[1-9]\d{0,19}", bot_id)
                or not isinstance(session_id, str)
                or not re.fullmatch(r"(?:private|group)_[1-9]\d{0,19}", session_id)):
            raise ValueError("invalid plugin history scope")
        return f"chat:plugin_history:{bot_id}:{session_id}"

    def remember(self, bot_id, session_id, entry):
        key = self.key(bot_id, session_id)
        if not valid_entry(entry):
            raise ValueError("invalid acknowledged plugin history")
        with _lock:
            cache = self.backend.memory.plugin_histories
            cache[key] = merge_entries([*cache.get(key, []), entry])
            cache.move_to_end(key)
            while len(cache) > MAX_SESSIONS:
                cache.popitem(last=False)

    def persist(self, bot_id, session_id, entry):
        key = self.key(bot_id, session_id)
        if not valid_entry(entry):
            raise ValueError("invalid acknowledged plugin history")
        client = self.redis
        if client is None:
            raise ConnectionError("plugin history Redis unavailable")
        return client.eval(_APPEND, 1, key, json.dumps(entry, ensure_ascii=False), LIMIT)

    def read(self, bot_id, session_id):
        if not bot_id:
            return []
        key = self.key(bot_id, session_id)
        rows = []
        try:
            client = self.redis
            if client is not None:
                for raw in client.lrange(key, -LIMIT, -1):
                    try:
                        rows.append(json.loads(raw))
                    except (TypeError, ValueError):
                        logger.warning("Invalid plugin history row skipped")
        except Exception:
            logger.warning("Plugin history unavailable; using acknowledged memory mirror")
        with _lock:
            cached = self.backend.memory.plugin_histories.get(key, [])
            result = merge_entries([*rows, *cached])
            if result:
                self.backend.memory.plugin_histories[key] = result
                self.backend.memory.plugin_histories.move_to_end(key)
                while len(self.backend.memory.plugin_histories) > MAX_SESSIONS:
                    self.backend.memory.plugin_histories.popitem(last=False)
        return [dict(row) for row in result]
