"""Persist source, revision and desired scheduler state in one Redis operation."""

TRANSITION = r"""
local op, id, expected, expected_rev, payload, new_rev, bot, due, grace, inspect_action = unpack(ARGV)
for i = 1, 3 do
    local t = redis.call('TYPE', KEYS[i]).ok
    if t ~= 'none' and t ~= 'hash' then return redis.error_reply('invalid reminder key type') end
end
local raw = redis.call('HGET', KEYS[1], id)
local rev = redis.call('HGET', KEYS[2], id) or ''
local intent_raw = redis.call('HGET', KEYS[3], id) or ''
local meta = nil
if intent_raw ~= '' then
    local valid, decoded = pcall(cjson.decode, intent_raw)
    if not valid or type(decoded) ~= 'table' or type(decoded.revision) ~= 'string'
        or type(decoded.bot_id) ~= 'string' or type(decoded.operation) ~= 'string' then
        return redis.error_reply('invalid reminder intent')
    end
    meta = decoded
end
local phase = 'uninspected'
local function result(ok, code)
    return {ok, code, raw or '', rev, intent_raw, phase}
end
if op == 'load' then return result(1, raw and (rev == '' and 'legacy' or 'loaded') or 'missing') end
local tm = redis.call('TIME')
local now = tonumber(tm[1]) * 1000 + math.floor(tonumber(tm[2]) / 1000)
if op == 'create' then
    -- Explicit recreation gets a fresh revision; old execution evidence stays.
    if raw or (meta and meta.operation ~= 'cancel') then return result(0, 'exists') end
    if rev ~= '' and not meta then return result(0, 'inconsistent') end
else
    if not raw then
        if op == 'complete' and meta and meta.reason == 'complete'
            and meta.revision == expected_rev and meta.action_key == KEYS[4] then
            phase = 'sent'
            return result(1, 'already_completed')
        end
        return result(0, 'missing')
    end
    if raw ~= expected or rev ~= expected_rev then return result(0, 'changed') end
end
if inspect_action == 'yes' then
    local action_raw = redis.call('GET', KEYS[4])
    phase = 'not_started'
    if action_raw then
        local valid, action = pcall(cjson.decode, action_raw)
        if not valid or type(action) ~= 'table' or action.schema_version ~= 1
            or type(action.spec_json) ~= 'string' or type(action.state) ~= 'string'
            or type(action.lease_until_ms) ~= 'number' then
            return redis.error_reply('invalid reminder delivery state')
        end
        local spec_ok, spec = pcall(cjson.decode, action.spec_json)
        local source_ok, source = pcall(cjson.decode, raw)
        if not spec_ok or not source_ok or type(spec) ~= 'table' or type(source) ~= 'table'
            or not meta or spec.kind ~= 'reminder' or spec.business_id ~= id
            or spec.revision ~= rev or spec.bot_id ~= meta.bot_id
            or spec.source_key ~= KEYS[1] or spec.source_field ~= id
            or spec.source_digest ~= redis.sha1hex(raw) or spec.revision_key ~= KEYS[2]
            or spec.target_type ~= 'group' or spec.target_id ~= tostring(source.group_id) then
            return result(0, 'wrong_action')
        end
        phase = action.state
        if phase == 'sending' and now >= action.lease_until_ms then phase = 'unknown' end
    end
end
if op == 'create' or op == 'replace' or op == 'migrate' then
    if not tonumber(due) or tonumber(due) <= now then return result(0, 'overdue') end
    if op == 'migrate' and (rev ~= '' or meta) then return result(0, 'already_versioned') end
    if op == 'replace' and meta and meta.bot_id ~= '' and meta.bot_id ~= bot then
        return result(0, 'wrong_bot')
    end
    raw = op == 'migrate' and raw or payload
    rev = new_rev
    meta = {revision=rev, bot_id=bot, operation='upsert', remind_at_ms=tonumber(due),
            grace_seconds=tonumber(grace)}
    intent_raw = cjson.encode(meta)
    redis.call('HSET', KEYS[1], id, raw)
    redis.call('HSET', KEYS[2], id, rev)
    redis.call('HSET', KEYS[3], id, intent_raw)
elseif op == 'bind' then
    if not meta or rev == '' or meta.revision ~= rev or meta.operation ~= 'upsert' then
        return result(0, 'not_versioned')
    end
    if meta.bot_id ~= '' and meta.bot_id ~= bot then return result(0, 'wrong_bot') end
    meta.bot_id = bot
    intent_raw = cjson.encode(meta)
    redis.call('HSET', KEYS[3], id, intent_raw)
elseif op == 'cancel' or op == 'complete' then
    if op == 'complete' and phase ~= 'sent' then return result(0, 'not_confirmed') end
    meta = {revision=rev, bot_id=meta and meta.bot_id or '', operation='cancel',
            reason=op, changed_at_ms=now, action_key=inspect_action == 'yes' and KEYS[4] or ''}
    intent_raw = cjson.encode(meta)
    redis.call('HDEL', KEYS[1], id)
    redis.call('HSET', KEYS[3], id, intent_raw)
    raw = nil
else return redis.error_reply('invalid reminder operation') end
return result(1, 'persisted')
"""
