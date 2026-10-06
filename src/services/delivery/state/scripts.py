"""Single-key Redis transitions; records deliberately have no expiry."""
from ..effects.activation import HELPERS

TRANSITION = HELPERS + r"""
local op, digest, token, raw = ARGV[1], ARGV[2], ARGV[3], ARGV[4]
local queue_ms, sending_ms = tonumber(ARGV[5]), tonumber(ARGV[6])
local tm = redis.call('TIME')
local now = tonumber(tm[1]) * 1000 + math.floor(tonumber(tm[2]) / 1000)
local stored = redis.call('GET', KEYS[1])
local s = nil
if stored then
    local valid, record = pcall(cjson.decode, stored)
    if not valid or type(record) ~= 'table' or record.schema_version ~= 1
        or type(record.state) ~= 'string' or type(record.token) ~= 'string'
        or type(record.digest) ~= 'string' or type(record.spec_json) ~= 'string'
        or type(record.lease_until_ms) ~= 'number'
        or type(record.valid_until_ms) ~= 'number' then
        return redis.error_reply('invalid delivery record')
    end
    s = record
end
local function result(ok, code)
    return {ok, code, s and s.state or '', tostring(s and s.lease_until_ms or 0),
            s and s.spec_json or ''}
end
local function save(state)
    s.state, s.updated_at_ms = state, now
    redis.call('SET', KEYS[1], cjson.encode(s))
end
if s and s.state == 'sending' and now >= s.lease_until_ms then save('unknown') end
if op == 'inspect' then return result(1, s and 'observed' or 'missing') end
if op == 'recover' then
    if not s then return result(0, 'missing') end
    op = 'claim'
end
if op == 'reconcile_sent' or op == 'reconcile_cancelled' then
    if not s then return result(0, 'missing') end
    if s.digest ~= digest then return result(0, 'changed') end
    local operator = ARGV[7]
    if not operator or not string.match(operator, '^%d+$') or #operator > 32 then
        return redis.error_reply('invalid reconciliation operator')
    end
    local target = op == 'reconcile_sent' and 'sent' or 'cancelled'
    if s.state == target and s.reconciled_as == target then
        return result(1, 'already_reconciled')
    end
    if s.state ~= 'unknown' then return result(0, 'blocked') end
    s.reconciled_as, s.reconciled_by, s.reconciled_at_ms = target, operator, now
    if target == 'sent' then activate_effects(s, 'owner', now) end
    save(target)
    return result(1, 'reconciled')
end
if op == 'claim' or op == 'begin' then
    local valid, spec = pcall(cjson.decode, raw)
    if not valid or type(spec) ~= 'table' then return redis.error_reply('invalid delivery source') end
    if spec.source_key and spec.source_key ~= '' then
        local source = redis.call('HGET', KEYS[2], spec.source_field)
        local revision = redis.call('HGET', KEYS[3], spec.source_field)
        if not source or redis.sha1hex(source) ~= spec.source_digest or revision ~= spec.revision then
            return result(0, 'source_changed')
        end
    end
end
if op == 'claim' then
    if s then
        if s.digest ~= digest then return result(0, 'changed') end
        if s.state ~= 'queued' and s.state ~= 'rejected_before_send' then
            return result(0, 'blocked')
        end
        if s.state == 'queued' and now < s.lease_until_ms then return result(0, 'busy') end
        if now >= s.valid_until_ms then return result(0, 'expired') end
    else
        local valid, spec = pcall(cjson.decode, raw)
        if not valid or type(spec) ~= 'table' or type(spec.valid_until_ms) ~= 'number' then
            return redis.error_reply('invalid delivery specification')
        end
        if now >= spec.valid_until_ms then return result(0, 'expired') end
        s = {schema_version=1, digest=digest, spec_json=raw,
             valid_until_ms=spec.valid_until_ms, created_at_ms=now, effects_state='not_started'}
    end
    install_plan(s)
    s.token, s.lease_until_ms = token, now + queue_ms
    save('queued')
    return result(1, 'claimed')
end
if not s or token == '' or s.token ~= token then return result(0, 'fenced') end
if op == 'begin' then
    if s.digest ~= digest then return result(0, 'changed') end
    if s.state ~= 'queued' then return result(0, 'blocked') end
    if now >= s.lease_until_ms or now >= s.valid_until_ms then return result(0, 'expired') end
    if s.effects_version ~= nil then validate_dormant(s)
    elseif ARGV[11] == 'yes' then return result(0, 'plan_required') end
    s.lease_until_ms = now + sending_ms
    save('sending')
elseif op == 'sent' then
    if s.state == 'sent' then return result(1, 'already_sent') end
    if s.state ~= 'sending' and s.state ~= 'unknown' then return result(0, 'blocked') end
    activate_effects(s, 'transport', now)
    save('sent')
elseif op == 'unknown' then
    if s.state ~= 'queued' and s.state ~= 'sending' and s.state ~= 'unknown' then
        return result(0, 'blocked')
    end
    -- A lost begin response can race its worker thread. Conservatively freeze
    -- even queued state; the same token can never subsequently start a send.
    save('unknown')
elseif op == 'reject' or op == 'cancel' then
    if s.state ~= 'queued' then return result(0, 'blocked') end
    save(op == 'cancel' and 'cancelled' or 'rejected_before_send')
else
    return redis.error_reply('invalid delivery operation')
end
return result(1, 'transitioned')
"""
