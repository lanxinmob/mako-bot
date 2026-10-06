"""Reminder source completion fragment; scheduler intents remain durable."""

APPLY = r"""
require_type(KEYS[3], 'hash')
require_type(KEYS[4], 'hash')
require_type(KEYS[5], 'hash')
local raw = redis.call('HGET', KEYS[3], spec.source_field)
local revision = redis.call('HGET', KEYS[4], spec.source_field)
local intent_raw = redis.call('HGET', KEYS[5], spec.source_field)
local intent = decode(intent_raw)
if not raw and not intent_raw then return 'missing' end
if not intent or type(intent.revision) ~= 'string' or not revision or revision == ''
    or intent.revision ~= revision or type(intent.bot_id) ~= 'string'
    or type(intent.operation) ~= 'string' then
    return 'inconsistent'
end
if not raw then
    if revision == spec.revision and intent.bot_id == spec.bot_id
        and intent.operation == 'cancel' and intent.reason == 'cancel'
        and (intent.action_key == '' or intent.action_key == KEYS[2]) then
        return finish('cancelled')
    end
    -- A legacy completion tombstone is not this effect's permanent receipt.
    -- No source body means that its original digest cannot be revalidated here.
    return 'inconsistent'
end
local source = decode(raw)
if not source or source.reminder_id ~= spec.business_id
    or tostring(source.group_id) ~= spec.target_id or type(source.content) ~= 'string'
    or intent.operation ~= 'upsert' or intent.bot_id == '' then
    return 'inconsistent'
end
if revision ~= spec.revision then return finish('superseded') end
if intent.bot_id ~= spec.bot_id or redis.sha1hex(raw) ~= spec.source_digest then
    return 'inconsistent'
end
local completed = cjson.encode({revision=revision, bot_id=intent.bot_id, operation='cancel',
    reason='complete', changed_at_ms=now, action_key=KEYS[2]})
begin_effect()
redis.call('HDEL', KEYS[3], spec.source_field)
redis.call('HSET', KEYS[5], spec.source_field, completed)
return finish('applied')
"""
