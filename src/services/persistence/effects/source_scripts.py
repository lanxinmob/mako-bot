"""Shared action authorization and permanent source-completion receipt."""

PREFIX = r"""
local binding, effect_id, action_id, spec_json, payload, kind, completed_at, spec_digest = unpack(ARGV)
local function require_type(key, wanted)
    local actual = redis.call('TYPE', key).ok
    if actual ~= 'none' and actual ~= wanted then error('invalid source effect key type') end
end
local function decode(raw)
    if not raw then return nil end
    local ok, value = pcall(cjson.decode, raw)
    if not ok or type(value) ~= 'table' then return nil end
    return value
end
require_type(KEYS[1], 'string')
local previous = redis.call('GET', KEYS[1])
if previous then
    local receipt = decode(previous)
    if not receipt or receipt.schema_version ~= 1 or type(receipt.binding) ~= 'string'
        or (receipt.result ~= 'applied' and receipt.result ~= 'superseded'
            and receipt.result ~= 'cancelled' and receipt.result ~= 'started') then
        error('invalid source effect receipt')
    end
    if receipt.binding ~= binding then return 'conflict' end
    if receipt.result == 'started' then return 'incomplete' end
    return receipt.result == 'applied' and 'already_applied' or receipt.result
end
require_type(KEYS[2], 'string')
local action = decode(redis.call('GET', KEYS[2]))
if not action or action.schema_version ~= 1 or action.state ~= 'sent'
    or action.spec_json ~= spec_json or action.digest ~= spec_digest
    or action.effects_version ~= 1 or type(action.effects) ~= 'table' then
    return 'wrong_action'
end
local matched = nil
for _, task in pairs(action.effects) do
    if type(task) ~= 'table' then return 'wrong_action' end
    if task.effect_id == effect_id then
        if matched then return 'wrong_action' end
        matched = task
    end
end
if not matched or matched.kind ~= kind or matched.codec_version ~= 1
    or matched.payload_json ~= payload or matched.payload_digest ~= redis.sha1hex(payload)
    or (matched.state ~= 'pending' and matched.state ~= 'retry_wait' and matched.state ~= 'leased') then
    return 'wrong_action'
end
local spec = decode(spec_json)
if not spec then return 'wrong_action' end
local tm = redis.call('TIME')
local now = tonumber(tm[1]) * 1000 + math.floor(tonumber(tm[2]) / 1000)
local function finish(code)
    local receipt = cjson.encode({schema_version=1, binding=binding, result=code,
        action_id=action_id, effect_id=effect_id, kind=kind, spec_digest=spec_digest,
        revision=spec.revision, source_digest=spec.source_digest, completed_at_ms=now})
    redis.call('SET', KEYS[1], receipt)
    return code
end
local function begin_effect()
    redis.call('SET', KEYS[1], cjson.encode({schema_version=1, binding=binding,
        result='started', action_id=action_id, effect_id=effect_id, kind=kind,
        spec_digest=spec_digest, revision=spec.revision, source_digest=spec.source_digest,
        started_at_ms=now}))
end
"""
