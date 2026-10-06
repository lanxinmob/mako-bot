"""No operation can reacquire permission to call an existing attempt."""

from .index_scripts import INDEX

TRANSITION = INDEX + """
local raw = redis.call('GET', KEYS[1])
local op, spec, token = ARGV[1], ARGV[2], ARGV[3]
if op == 'start' then
    if raw then return 'exists' end
    local now = redis.call('TIME')
    local item = {schema_version=1, spec_json=spec, token=token, state='calling',
        started_at_ms=tonumber(now[1])*1000+math.floor(tonumber(now[2])/1000),
        cost_state='not_ready'}
    redis.call('SET', KEYS[1], cjson.encode(item))
    return 'started'
end
if not raw then return 'missing' end
local ok, item = pcall(cjson.decode, raw)
if not ok or type(item) ~= 'table' or item.schema_version ~= 1 then return 'invalid' end
if item.spec_json ~= spec or item.token ~= token then return 'conflict' end
if redis.call('PTTL', KEYS[1]) ~= -1 then return 'invalid' end
if op == 'unknown' then
    if item.state == 'completed' then return 'completed' end
    if item.state == 'unknown' then return 'unknown' end
    if item.state ~= 'calling' then return 'invalid' end
    item.state = 'unknown'
    item.cost_state = 'needs_review'
elseif op == 'complete' then
    local amount = ARGV[4]
    if item.state == 'completed' then
        if item.amount_json == amount then
            if not sync_index(item, ARGV[5]) then return 'index_unconfirmed' end
            return 'completed'
        end
        return 'conflict'
    end
    if item.state ~= 'calling' and item.state ~= 'unknown' then return 'invalid' end
    item.state = 'completed'
    item.amount_json = amount
    item.cost_state = tonumber(amount) == 0 and 'complete' or 'pending'
else return 'invalid' end
redis.call('SET', KEYS[1], cjson.encode(item))
if not sync_index(item, ARGV[5]) then return 'index_unconfirmed' end
return item.state
"""
