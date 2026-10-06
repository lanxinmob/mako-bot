"""One-command session replacement and permanent outcome evidence."""

APPLY = """
local receipt_type = redis.call('TYPE', KEYS[1]).ok
if receipt_type ~= 'none' and receipt_type ~= 'string' then
    return redis.error_reply('invalid history receipt type')
end
local receipt = redis.call('GET', KEYS[1])
if receipt then
    if redis.call('PTTL', KEYS[1]) ~= -1 then
        return redis.error_reply('unexpected history receipt TTL')
    end
    if receipt == 'applied:' .. ARGV[1] then return 'already_applied' end
    if receipt == 'conflict:' .. ARGV[1] then return 'history_conflict' end
    return 'identity_conflict'
end
local source, expected = ARGV[2], ARGV[3]
local current_type = redis.call('TYPE', KEYS[2]).ok
local matched = false
if source == 'current' then
    matched = current_type == 'string' and redis.call('GET', KEYS[2]) == expected
elseif current_type == 'none' then
    local legacy_type = redis.call('TYPE', KEYS[3]).ok
    if source == 'legacy' then
        matched = legacy_type == 'string' and redis.call('GET', KEYS[3]) == expected
    elseif source == 'missing' then matched = legacy_type == 'none' end
end
if not matched then
    -- Remember a terminal conflict even if someone later restores the old bytes.
    redis.call('SET', KEYS[1], 'conflict:' .. ARGV[1])
    return 'history_conflict'
end
-- No target mutation precedes this command. Legacy evidence is never deleted.
redis.call('MSET', KEYS[2], ARGV[4], KEYS[1], 'applied:' .. ARGV[1])
return 'applied'
"""
