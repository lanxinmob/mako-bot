"""One CAS grants or settles one task, preserving its independent sibling."""

TRANSITION = """
local kind = redis.call('TYPE', KEYS[1]).ok
if kind == 'none' then return '' end
if kind ~= 'string' then return redis.error_reply('invalid chat effect type') end
local raw = redis.call('GET', KEYS[1])
if raw ~= ARGV[1] then return '' end
if redis.call('PTTL', KEYS[1]) ~= -1 then
    return redis.error_reply('unexpected chat effect TTL')
end
local item = cjson.decode(raw)
if item.state ~= 'sent' then return '' end
local task, op, token = ARGV[2], ARGV[3], ARGV[4]
local state = item.tasks[task]
local metadata = item.task_meta or {}
local m = metadata[task] or {attempts=0, token='', lease_until_ms=0,
    next_attempt_at_ms=0, result=''}
local tm = redis.call('TIME')
local now = tonumber(tm[1])*1000+math.floor(tonumber(tm[2])/1000)
if now + math.max(tonumber(ARGV[5]), 3600000) > 99999999999999 then
    return redis.error_reply('chat effect time capacity exceeded')
end
if op == 'claim' then
    if state ~= 'pending' and state ~= 'leased' and state ~= 'retry_wait' then return '' end
    if state == 'leased' and now < m.lease_until_ms then return '' end
    if state == 'retry_wait' and now < m.next_attempt_at_ms then return '' end
    item.tasks[task], m.token = 'leased', token
    m.attempts = math.min(m.attempts + 1, 2147483647)
    m.lease_until_ms, m.next_attempt_at_ms, m.result = now + tonumber(ARGV[5]), 0, ''
else
    if m.token ~= token then return '' end
    if m.result == ARGV[6] and
        (state == 'retry_wait' or state == 'complete' or state == 'needs_review') then return raw end
    if state ~= 'leased' or now >= m.lease_until_ms then return '' end
    if op == 'defer' then
        item.tasks[task] = 'retry_wait'
        m.next_attempt_at_ms = now + math.min(3600000, 1000*2^math.min(m.attempts,12))
    elseif op == 'finish' then
        if ARGV[6] == 'applied' or ARGV[6] == 'already_applied' then
            item.tasks[task] = 'complete'
        else item.tasks[task] = 'needs_review' end
        m.next_attempt_at_ms = 0
    else return '' end
    m.lease_until_ms, m.result = 0, ARGV[6]
end
metadata[task], item.task_meta = m, metadata
local saved = cjson.encode(item)
redis.call('SET', KEYS[1], saved)
return saved
"""
