"""Reserve original intents under the C2 pending barrier; metadata-only receipts."""
from .codec import ENCODE

PREFIX = ENCODE + r'''
local op, id, encoded = unpack(ARGV)
local kinds = {'hash','hash','hash','zset','hash','hash','hash','string','string'}
for i, wanted in ipairs(kinds) do
    local actual = redis.call('TYPE', KEYS[i]).ok
    if actual ~= 'none' and actual ~= wanted then error('invalid companion key type') end
end
local tm = redis.call('TIME')
local now = tonumber(tm[1])*1000 + math.floor(tonumber(tm[2])/1000)
local function decode(raw) return raw and cjson.decode(raw) or nil end
local control = decode(redis.call('HGET',KEYS[7],'state')) or {revision=0,controlled=false,cutoff_ns=0}
local pending = 'companion:'..id
local seen = redis.call('HGET',KEYS[5],'seen:'..id)
if seen == 'complete' then
    return redis.call('HGET',KEYS[5],'result:'..id) or '{"status":"already_processed"}'
end
local function complete(answer)
    answer.plan_id = answer.plan_id or ''
    local raw = cjson.encode(answer)
    redis.call('HSET',KEYS[5],'seen:'..id,'complete','result:'..id,raw)
    redis.call('HDEL',KEYS[5],'intent:'..id)
    local order = decode(redis.call('HGET',KEYS[5],'order')) or {}
    table.insert(order,id)
    while #order > 100 do redis.call('HDEL',KEYS[5],'result:'..table.remove(order,1)) end
    redis.call('HSET',KEYS[5],'order',cjson.encode(order))
    if control.pending == pending then
        control.pending = nil
        redis.call('HSET',KEYS[7],'state',cjson.encode(control))
    end
    return raw
end
if op == 'reserve' then
    if seen == 'pending' then return '{"status":"pending"}' end
    if control.pending then return '{"status":"busy"}' end
    local intent = cjson.decode(encoded)
    if control.revision ~= intent.memory_revision then return complete({status='conflict'}) end
    control.pending = pending
    redis.call('HSET',KEYS[7],'state',cjson.encode(control))
    redis.call('HSET',KEYS[5],'seen:'..id,'pending','intent:'..id,encoded)
    return '{"status":"pending"}'
end
if op ~= 'apply' or seen ~= 'pending' or control.pending ~= pending then
    return '{"status":"unconfirmed"}'
end
local intent = decode(redis.call('HGET',KEYS[5],'intent:'..id))
if not intent or control.revision ~= intent.memory_revision then return complete({status='conflict'}) end
local pid, operation = intent.plan_id, intent.operation
local raw = redis.call('HGET',KEYS[1],pid)
if (intent.expected == false and raw) or (intent.expected ~= false and raw ~= intent.expected) then
    return complete({status='conflict',plan_id=pid})
end
local plan = decode(raw)
local original_consent = plan and plan.consent or 'none'
local note_id = plan and plan.note_id or intent.plan.note_id
local note = decode(redis.call('HGET',KEYS[6],note_id))
if note and (note.user_id ~= tonumber(intent.user_id) or note.category ~= 'companion'
    or note.visibility ~= 'private' or note.title ~= '考试计划:'..pid) then
    return complete({status='conflict',plan_id=pid})
end
if not plan and note then return complete({status='conflict',plan_id=pid}) end
local function stop(step, status)
    redis.call('HDEL',KEYS[3],pid..':'..step)
    redis.call('ZREM',KEYS[4],intent.user_id..':'..pid..':'..step)
    if plan.steps[step] and plan.steps[step].status ~= 'finished' then plan.steps[step].status = status end
end
local function unstarted(key)
    local action = decode(redis.call('GET',key))
    if not action then return true end
    return action.state == 'queued' or action.state == 'rejected_before_send'
        or (action.state == 'cancelled' and not action.reconciled_as)
end
'''
