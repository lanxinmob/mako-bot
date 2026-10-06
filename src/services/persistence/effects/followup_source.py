"""Followup source completion fragment, after shared action authorization."""

APPLY = r"""
require_type(KEYS[3], 'hash')
require_type(KEYS[4], 'hash')
require_type(KEYS[5], 'zset')
local raw = redis.call('HGET', KEYS[3], spec.source_field)
local revision = redis.call('HGET', KEYS[4], spec.source_field)
if not raw then return 'missing' end
local source = decode(raw)
if not source or source.memory_id ~= spec.business_id
    or tostring(source.user_id) ~= spec.target_id
    or type(source.content) ~= 'string' or type(source.status) ~= 'string'
    or not revision or revision == '' then
    return 'inconsistent'
end
if revision ~= spec.revision then return finish('superseded') end
if redis.sha1hex(raw) ~= spec.source_digest or source.status ~= 'active'
    or type(source.due_at) ~= 'string' then
    return 'inconsistent'
end
source.status = 'done'
source.updated_at, source.last_used_at = completed_at, completed_at
local updated = cjson.encode(source)
begin_effect()
redis.call('HSET', KEYS[3], spec.source_field, updated)
redis.call('ZREM', KEYS[5], spec.target_id .. ':' .. spec.business_id)
return finish('applied')
"""
