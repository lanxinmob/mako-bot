"""Persist send eligibility separately from historical effect eligibility."""

CREATE = """
local kind = redis.call('TYPE', KEYS[1]).ok
if kind ~= 'none' then return 'exists' end
local tm = redis.call('TIME')
local now = tonumber(tm[1])*1000+math.floor(tonumber(tm[2])/1000)
if now < 1 or now > 99999999999999 then
    return redis.error_reply('chat creation time capacity exceeded')
end
local item = {version=1, plan_json=ARGV[1], digest=ARGV[2], token=ARGV[3],
    state='prepared', created_at_ms=now, tasks={session='dormant', global='dormant'}}
redis.call('SET', KEYS[1], cjson.encode(item))
return 'created'
"""

TRANSITION = """
local kind = redis.call('TYPE', KEYS[1]).ok
if kind == 'none' then return 'missing' end
if kind ~= 'string' then return redis.error_reply('invalid chat delivery type') end
local raw = redis.call('GET', KEYS[1])
if raw ~= ARGV[1] then return 'changed' end
if redis.call('PTTL', KEYS[1]) ~= -1 then
    return redis.error_reply('unexpected chat delivery TTL')
end
local item = cjson.decode(raw)
local op, token = ARGV[2], ARGV[3]
if item.token ~= token then return 'denied' end
if item.confirmation_source == 'owner' then return 'denied' end
local tm = redis.call('TIME')
local now = tonumber(tm[1])*1000+math.floor(tonumber(tm[2])/1000)
if op == 'begin' then
    if item.state ~= 'prepared' then return 'denied' end
    if now < 1 or now > 99999999999999 then
        return redis.error_reply('chat begin time capacity exceeded')
    end
    item.state, item.begun_at_ms = 'sending', now
elseif op == 'sent' then
    local delivered = tonumber(ARGV[4])
    if item.state == 'sent' then
        if item.delivered_at_ms == delivered then return 'sent' end
        return 'denied'
    end
    if item.state ~= 'sending' and item.state ~= 'unknown' then return 'denied' end
    item.state, item.delivered_at_ms = 'sent', delivered
    item.tasks = {session='pending', global='pending'}
elseif op == 'unknown' then
    if item.state == 'unknown' then return 'unknown' end
    if item.state ~= 'sending' then return 'denied' end
    item.state = 'unknown'
elseif op == 'reject' then
    if item.state == 'rejected' then return 'rejected' end
    if item.state ~= 'prepared' then return 'denied' end
    item.state = 'rejected'
else return 'denied' end
redis.call('SET', KEYS[1], cjson.encode(item))
return item.state
"""
