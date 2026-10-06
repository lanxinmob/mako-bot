"""Single action-key CAS; target writes belong to separate idempotent adapters."""

TRANSITION = r"""
local expected, id, digest, op, token, lease_ms, outcome = unpack(ARGV)
local raw = redis.call('GET', KEYS[1])
if not raw then return {0, 'missing', ''} end
if raw ~= expected then return {0, 'changed', ''} end
-- Python verified this exact byte snapshot; CAS prevents concurrent mutation
-- from invalidating that validation before the final single SET.
local action = cjson.decode(raw)
local task = nil
for _, candidate in ipairs(action.effects) do
    if candidate.effect_id == id then task = candidate end
end
if not task or task.payload_digest ~= digest then return {0, 'changed', ''} end
local tm = redis.call('TIME')
local now = tonumber(tm[1]) * 1000 + math.floor(tonumber(tm[2]) / 1000)
local function aggregate()
    local review, pending, skipped = false, false, false
    for _, effect in ipairs(action.effects) do
        if effect.state == 'needs_review' then review = true
        elseif effect.state == 'skipped' then skipped = true
        elseif effect.state ~= 'complete' then pending = true end
    end
    if review then return 'needs_review' end
    if pending then return 'pending' end
    return skipped and 'complete_with_skips' or 'complete'
end
if op == 'claim' then
    if (task.state == 'leased' and now < task.lease_until_ms)
        or (task.state == 'retry_wait' and now < task.next_attempt_at_ms) then
        return {0, 'busy', ''}
    end
    if task.state ~= 'pending' and task.state ~= 'retry_wait' and task.state ~= 'leased' then
        return {0, 'terminal', ''}
    end
    task.state, task.lease_token = 'leased', token
    task.lease_until_ms = now + tonumber(lease_ms)
    task.attempts = math.min(task.attempts + 1, 2147483647)
elseif op == 'finish' or op == 'defer' then
    if task.lease_token ~= token or token == '' then return {0, 'fenced', ''} end
    if op == 'defer' and task.state == 'retry_wait' and task.result_code == outcome then
        return {1, 'already_deferred', cjson.encode(task)}
    end
    if op == 'finish' and (task.state == 'complete' or task.state == 'skipped'
        or task.state == 'needs_review') and task.result_code == outcome then
        return {1, 'already_finished', cjson.encode(task)}
    end
    if task.state ~= 'leased' or now >= task.lease_until_ms then return {0, 'fenced', ''} end
    if op == 'defer' then
        task.state = 'retry_wait'
        task.next_attempt_at_ms = now + math.min(3600000, 1000 * 2 ^ math.min(task.attempts, 12))
    elseif outcome == 'applied' or outcome == 'already_applied' then task.state = 'complete'
    elseif outcome == 'superseded' or outcome == 'cancelled' then task.state = 'skipped'
    else task.state = 'needs_review' end
    task.result_code, task.lease_until_ms = outcome, 0
else return redis.error_reply('invalid effect operation') end
action.effects_state = aggregate()
local saved = cjson.encode(action)
redis.call('SET', KEYS[1], saved)
return {1, 'persisted', cjson.encode(task)}
"""
