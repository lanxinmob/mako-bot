"""Atomic source revisions for durable followups; legacy records stay unsent."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from src.models.schemas import RelationshipMemory


SCRIPT = r"""
local op, field, expected, payload, revision, due = unpack(ARGV)
local function check(key, wanted)
    local t = redis.call('TYPE', key).ok
    if t ~= 'none' and t ~= wanted then return false end
    return true
end
if not check(KEYS[1], 'hash') or not check(KEYS[2], 'hash')
    or not check(KEYS[3], 'zset') or not check(KEYS[4], 'zset') then
    return redis.error_reply('invalid followup key type')
end
local raw = redis.call('HGET', KEYS[1], field)
local current_revision = redis.call('HGET', KEYS[2], field)
local member = ARGV[7]
if op == 'create' then
    if raw then return 0 end
    redis.call('HSET', KEYS[1], field, payload)
    if due ~= '' then
        redis.call('HSET', KEYS[2], field, revision)
        redis.call('ZADD', KEYS[3], due, member)
    end
    return 1
end
if op == 'load' then
    if not raw then return {} end
    local score = redis.call('ZSCORE', KEYS[3], member)
    local tm = redis.call('TIME')
    if not score or tonumber(score) > tonumber(tm[1]) + tonumber(tm[2]) / 1000000 then return {} end
    if not current_revision then
        -- Keep business data, quarantine legacy work instead of treating it as
        -- newly created. Removal from the due index prevents scan starvation.
        redis.call('ZADD', KEYS[4], score, member)
        redis.call('ZREM', KEYS[3], member)
        return {}
    end
    return {raw, current_revision}
end
if not raw then return 0 end
if op == 'done' then
    if current_revision ~= revision then return 0 end
    if raw ~= expected then
        local valid, value = pcall(cjson.decode, raw)
        if valid and type(value) == 'table' and value.status == 'done' then
            -- A legacy writer can persist done and lose its ZREM response.
            -- Same revision still needs the complete index postcondition.
            redis.call('ZREM', KEYS[3], member)
            return 1
        end
        return 0
    end
elseif raw ~= expected then return 0 end
if op == 'delete' then
    redis.call('HDEL', KEYS[1], field)
    redis.call('HDEL', KEYS[2], field)
    redis.call('ZREM', KEYS[3], member)
    redis.call('ZREM', KEYS[4], member)
elseif op == 'update' or op == 'done' then
    redis.call('HSET', KEYS[1], field, payload)
    if op == 'done' then
        redis.call('ZREM', KEYS[3], member)
    elseif current_revision then
        redis.call('HSET', KEYS[2], field, revision)
    end
else return redis.error_reply('invalid followup operation') end
return 1
"""


def revision_key(user_id):
    return f"mako:delivery:v1:source:followup:{user_id}"


def mutate(client, operation, user_id, memory_id, *, expected="", payload="", revision="", due=""):
    return client.eval(SCRIPT, 4, f"relationship:{user_id}", revision_key(user_id),
                       "relationship:followups", "mako:delivery:v1:legacy:followups",
                       operation, memory_id, expected, payload, revision, due,
                       f"{user_id}:{memory_id}")


@dataclass(frozen=True)
class FollowupSnapshot:
    memory: RelationshipMemory
    raw: str
    revision: str

    @property
    def digest(self):
        return hashlib.sha1(self.raw.encode("utf-8")).hexdigest()


class FollowupSource:
    def __init__(self, redis_client):
        if redis_client is None:
            raise RuntimeError("followup delivery requires Redis")
        self.redis = redis_client

    def load(self, user_id, memory_id):
        values = mutate(self.redis, "load", user_id, memory_id)
        if not values:
            return None
        raw, revision = [v.decode("utf-8") if isinstance(v, bytes) else v for v in values]
        memory = RelationshipMemory.model_validate_json(raw)
        if (memory.user_id != user_id or memory.memory_id != memory_id
                or memory.status != "active" or memory.due_at is None):
            return None
        return FollowupSnapshot(memory, raw, revision)

    def complete(self, snapshot):
        memory = snapshot.memory.model_copy(deep=True)
        memory.status = "done"
        memory.last_used_at = memory.updated_at = datetime.now()
        return bool(mutate(self.redis, "done", memory.user_id, memory.memory_id,
                           expected=snapshot.raw, revision=snapshot.revision,
                           payload=json.dumps(memory.model_dump(mode="json"), ensure_ascii=False)))
