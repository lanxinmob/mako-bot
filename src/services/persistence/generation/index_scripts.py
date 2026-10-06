"""Rebuildable discovery only; never roll back authoritative evidence."""

COST_DUE_KEY = "mako:generation:cost_due:v1"

SNAPSHOT = """
local kind = redis.call('TYPE', KEYS[1]).ok
if kind == 'string' then return {kind, redis.call('GET', KEYS[1])} end
return {kind}
"""

REMOVE_WRONG_TYPE = """
local kind = redis.call('TYPE', KEYS[1]).ok
if kind == 'none' or kind == 'string' or kind ~= ARGV[2] then return 'changed' end
redis.call('ZREM', KEYS[2], ARGV[1])
return 'removed_invalid'
"""

# Preflight both types before any state mutation. A broken discovery index must
# not prevent saving a provider result or a cost outcome already observed.
INDEX = """
local source_type = redis.call('TYPE', KEYS[1]).ok
if source_type ~= 'none' and source_type ~= 'string' then
    return redis.error_reply('invalid generation key type')
end
local index_type = redis.call('TYPE', KEYS[2]).ok
local function sync_index(item, id)
    if index_type ~= 'none' and index_type ~= 'zset' then return false end
    local score = nil
    if item and item.state == 'completed' then
        local amount = tonumber(item.amount_json)
        if not amount or amount < 0 then return false end
        if amount > 0 then
            if item.cost_state == 'pending' then
                score = 0
            elseif item.cost_state == 'leased' then
                score = item.cost_lease_until_ms
            elseif item.cost_state == 'retry_wait' then
                score = item.cost_next_attempt_at_ms
            elseif item.cost_state ~= 'complete' and item.cost_state ~= 'needs_review' then
                return false
            end
            if item.cost_state == 'pending' then
                local tm = redis.call('TIME')
                score = tonumber(tm[1])*1000+math.floor(tonumber(tm[2])/1000)
            elseif score ~= nil and type(score) ~= 'number' then return false end
            if (item.cost_state == 'leased' or item.cost_state == 'retry_wait')
                and score == nil then return false end
        elseif item.cost_state ~= 'complete' then return false end
    end
    local result
    if score ~= nil then
        result = redis.pcall('ZADD', KEYS[2], score, id)
    else
        result = redis.pcall('ZREM', KEYS[2], id)
    end
    return not (type(result) == 'table' and result.err)
end
"""

REPAIR = INDEX + """
local raw = redis.call('GET', KEYS[1])
local result_kind = ARGV[4]
if ARGV[1] == 'missing' then
    if raw then return 'changed' end
else
    if not raw or raw ~= ARGV[2] then return 'changed' end
    if redis.call('PTTL', KEYS[1]) ~= -1 then result_kind = 'removed_invalid' end
end
local item = nil
if raw and result_kind ~= 'removed_invalid' then item = cjson.decode(raw) end
-- Classification grants neither provider permission nor an estimated amount.
-- The exact snapshot and permanent-source checks above fence late completions.
if item and item.state == 'calling' then
    local tm = redis.call('TIME')
    local now = tonumber(tm[1])*1000+math.floor(tonumber(tm[2])/1000)
    if now - item.started_at_ms > 300000 then
        item.state, item.cost_state = 'unknown', 'needs_review'
        redis.call('SET', KEYS[1], cjson.encode(item))
    end
end
if not sync_index(item, ARGV[3]) then return 'index_unconfirmed' end
return result_kind
"""

DUE = """
local kind = redis.call('TYPE', KEYS[1]).ok
if kind ~= 'none' and kind ~= 'zset' then
    return redis.error_reply('invalid generation index type')
end
local tm = redis.call('TIME')
local now = tonumber(tm[1])*1000+math.floor(tonumber(tm[2])/1000)
return redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', now, 'LIMIT', 0, ARGV[1])
"""
