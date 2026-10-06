"""Target mutation and its permanent idempotency receipt share one script."""

APPLY = r"""
local digest, kind, raw = ARGV[1], ARGV[2], ARGV[3]
local function require_type(key, expected)
    local actual = redis.call('TYPE', key).ok
    if actual ~= 'none' and actual ~= expected then error('invalid effect target type') end
end
require_type(KEYS[1], 'string')
local receipt = redis.call('GET', KEYS[1])
if receipt then
    if receipt == digest then return 'already_applied' end
    if receipt == 'started:' .. digest then return 'incomplete' end
    return 'conflict'
end
local p = cjson.decode(raw)
if kind == 'history' or kind == 'outbound' then
    require_type(KEYS[2], 'list')
    -- A failed script does not roll back RPUSH. Persist uncertainty first so
    -- even loss of the error response cannot authorize another append.
    redis.call('SET', KEYS[1], 'started:' .. digest)
    redis.call('RPUSH', KEYS[2], p.record)
    redis.call('LTRIM', KEYS[2], -p.max_records, -1)
    if p.ttl > 0 then redis.call('EXPIRE', KEYS[2], p.ttl) end
elseif kind == 'cost' then
    require_type(KEYS[2], 'string')
    require_type(KEYS[3], 'string')
    local a = tonumber(redis.call('GET', KEYS[2]) or '0')
    local b = tonumber(redis.call('GET', KEYS[3]) or '0')
    if not a or not b or a ~= a or b ~= b then error('invalid effect cost value') end
    a, b = a + p.amount, b + p.amount
    if a ~= a or b ~= b or math.abs(a) == math.huge or math.abs(b) == math.huge then
        error('invalid effect cost sum')
    end
    -- Both totals and the receipt use one command, including on a lost reply.
    redis.call('MSET', KEYS[2], string.format('%.17g', a), KEYS[3], string.format('%.17g', b),
               KEYS[1], digest)
    redis.call('EXPIRE', KEYS[2], p.ttl)
    redis.call('EXPIRE', KEYS[3], p.ttl)
    return 'applied'
elseif kind == 'news' then
    require_type(KEYS[2], 'hash')
    for _, fingerprint in ipairs(p.fingerprints) do
        local previous = redis.call('HGET', KEYS[2], fingerprint)
        if previous then
            local value = tonumber(previous)
            if not value or value ~= value or math.abs(value) == math.huge then
                error('invalid news timestamp')
            end
        end
    end
    redis.call('SET', KEYS[1], 'started:' .. digest)
    for _, fingerprint in ipairs(p.fingerprints) do
        local previous = tonumber(redis.call('HGET', KEYS[2], fingerprint) or '0')
        if p.sent_at > previous then redis.call('HSET', KEYS[2], fingerprint, p.sent_at) end
    end
else
    error('invalid effect kind')
end
redis.call('SET', KEYS[1], digest)
return 'applied'
"""
