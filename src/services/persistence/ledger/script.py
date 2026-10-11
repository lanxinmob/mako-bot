"""Reserved intent + atomic application; no plaintext in completed receipts."""
SCRIPT = r'''
local op, id, encoded = unpack(ARGV)
local wanted = {'hash','hash','hash','hash','zset','zset','list'}
for i, kind in ipairs(wanted) do
    local actual = redis.call('TYPE', KEYS[i]).ok
    if actual ~= 'none' and actual ~= kind then return redis.error_reply('invalid ledger key type') end
end
local raw = redis.call('HGET', KEYS[1], 'state')
local state = raw and cjson.decode(raw) or {revision=0,controlled=false,cutoff_ns=0}
local seen = redis.call('HGET', KEYS[1], 'seen:'..id)
local result = redis.call('HGET', KEYS[1], 'result:'..id)
if seen == 'complete' then return result or '{"status":"already_processed"}' end
local function complete(answer)
    local completed = cjson.encode(answer)
    redis.call('HSET', KEYS[1], 'seen:'..id, 'complete', 'result:'..id, completed)
    redis.call('HDEL', KEYS[1], 'plan:'..id)
    redis.call('RPUSH', KEYS[7], id)
    while redis.call('LLEN', KEYS[7]) > 100 do
        local old = redis.call('LPOP', KEYS[7]); redis.call('HDEL', KEYS[1], 'result:'..old)
    end
    return completed
end
if op == 'reserve' then
    if seen == 'pending' then return '{"status":"pending"}' end
    if state.pending then return '{"status":"busy"}' end
    local plan = cjson.decode(encoded)
    if state.revision ~= plan.expected_revision then return complete({status='conflict', revision=state.revision}) end
    state.pending = id
    redis.call('HSET', KEYS[1], 'state', cjson.encode(state), 'seen:'..id, 'pending', 'plan:'..id, encoded)
    return '{"status":"pending"}'
end
if op ~= 'apply' or seen ~= 'pending' or state.pending ~= id then return '{"status":"unconfirmed"}' end
local plan = cjson.decode(redis.call('HGET', KEYS[1], 'plan:'..id))
local conflict = state.revision ~= plan.expected_revision
for field, expected in pairs(plan.expected) do
    local value = redis.call('HGET', KEYS[2], field)
    if (expected == false and value) or (expected ~= false and value ~= expected) then conflict = true end
end
for field, expected in pairs(plan.expected_notes) do
    local value = redis.call('HGET', KEYS[3], field)
    if (expected == false and value) or (expected ~= false and value ~= expected) then conflict = true end
end
local answer = {status=conflict and 'conflict' or plan.status, memory_id=plan.memory_id}
if not conflict and not plan.no_change then
    for field, value in pairs(plan.records) do redis.call('HSET', KEYS[2], field, value) end
    for _, field in ipairs(plan.delete_notes) do redis.call('HDEL', KEYS[3], field) end
    for field, value in pairs(plan.notes) do redis.call('HSET', KEYS[3], field, value) end
    for _, field in ipairs(plan.cancel) do
        redis.call('HDEL', KEYS[4], field)
        redis.call('ZREM', KEYS[5], plan.user_id..':'..field)
        redis.call('ZREM', KEYS[6], plan.user_id..':'..field)
    end
    for field, value in pairs(plan.due) do
        redis.call('HSET', KEYS[4], field, value.revision)
        redis.call('ZADD', KEYS[5], value.at, plan.user_id..':'..field)
    end
    state.revision = state.revision + 1
    if plan.controlled then state.controlled = true; state.cutoff_ns = plan.cutoff_ns end
    for field, value in pairs(plan.blocked) do
        if value then redis.call('HSET', KEYS[1], 'blocked:'..field, '1')
        else redis.call('HDEL', KEYS[1], 'blocked:'..field) end
    end
end
state.pending = nil
answer.revision = state.revision
redis.call('HSET', KEYS[1], 'state', cjson.encode(state))
return complete(answer)
'''
