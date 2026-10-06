"""Fence cost consumers independently of the model invocation token."""

from .index_scripts import INDEX

TRANSITION = INDEX + """
local raw = redis.call('GET', KEYS[1])
if not raw or raw ~= ARGV[1] then return '' end
if redis.call('PTTL', KEYS[1]) ~= -1 then return redis.error_reply('unexpected generation TTL') end
local item = cjson.decode(raw)
local op, token, outcome = ARGV[2], ARGV[3], ARGV[4]
local tm = redis.call('TIME')
local now = tonumber(tm[1])*1000+math.floor(tonumber(tm[2])/1000)
if op == 'claim' then
    if item.cost_state ~= 'pending' and item.cost_state ~= 'retry_wait'
        and item.cost_state ~= 'leased' then return '' end
    if item.cost_state == 'leased' and now < item.cost_lease_until_ms then return '' end
    if item.cost_state == 'retry_wait' and now < item.cost_next_attempt_at_ms then return '' end
    item.cost_state, item.cost_token = 'leased', token
    item.cost_attempts = math.min((item.cost_attempts or 0)+1, 2147483647)
    item.cost_lease_until_ms = now + 120000
else
    if item.cost_token ~= token then return '' end
    if item.cost_result == outcome and
        (item.cost_state == 'retry_wait' or item.cost_state == 'complete'
         or item.cost_state == 'needs_review') then
        if not sync_index(item, ARGV[5]) then return 'index_unconfirmed' end
        return raw
    end
    if item.cost_state ~= 'leased' or now >= item.cost_lease_until_ms then return '' end
    if outcome == 'unavailable' then
        item.cost_state = 'retry_wait'
        item.cost_next_attempt_at_ms = now + math.min(3600000, 1000*2^math.min(item.cost_attempts,12))
    elseif outcome == 'applied' or outcome == 'already_applied' then item.cost_state = 'complete'
    else item.cost_state = 'needs_review' end
    item.cost_result, item.cost_lease_until_ms = outcome, 0
end
local saved = cjson.encode(item)
redis.call('SET', KEYS[1], saved)
if not sync_index(item, ARGV[5]) then return 'index_unconfirmed' end
return saved
"""
