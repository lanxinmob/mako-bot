"""Lua helpers embedded in the action transition, with no separate queue write."""

HELPERS = r"""
local function plan_error() error('invalid frozen effect plan') end
local function read_plan(state)
    if state.effects_version ~= 1 or type(state.plan_json) ~= 'string'
        or #state.plan_json > 131072 or type(state.plan_digest) ~= 'string'
        or #state.plan_digest ~= 64 or type(state.plan_sha1) ~= 'string'
        or redis.sha1hex(state.plan_json) ~= state.plan_sha1 then plan_error() end
    local ok, plan = pcall(cjson.decode, state.plan_json)
    local spec_ok, spec = pcall(cjson.decode, state.spec_json)
    if not ok or not spec_ok or type(plan) ~= 'table' or type(spec) ~= 'table'
        or plan.version ~= 1 or plan.spec_digest ~= state.digest
        or plan.action_id ~= string.sub(KEYS[1], -64) or type(plan.tasks) ~= 'table'
        or #plan.tasks < 1 or #plan.tasks > 3 then plan_error() end
    local required = {}
    if spec.kind == 'reminder' then required.reminder_complete = true
    elseif spec.kind == 'followup' then
        required.followup_complete, required.outbound_dedup = true, true
    elseif spec.kind == 'periodic' then
        required.outbound_dedup, required.global_history = true, true
        local body_ok, body = pcall(cjson.decode, spec.payload)
        if not body_ok or type(body) ~= 'table' or type(body.fingerprints) ~= 'table' then plan_error() end
        if #body.fingerprints > 0 then required.news_fingerprints = true end
    else plan_error() end
    local ids, count = {}, 0
    for index, task in pairs(plan.tasks) do
        count = count + 1
        if type(index) ~= 'number' or index < 1 or index > #plan.tasks
            or type(task) ~= 'table' or task.codec_version ~= 1 or not required[task.kind]
            or type(task.effect_id) ~= 'string' or #task.effect_id ~= 64
            or not string.match(task.effect_id, '^[0-9a-f]+$') or ids[task.effect_id]
            or type(task.payload_json) ~= 'string' or #task.payload_json > 65536
            or task.payload_digest ~= redis.sha1hex(task.payload_json) then plan_error() end
        ids[task.effect_id], required[task.kind] = true, nil
        local payload_ok, p = pcall(cjson.decode, task.payload_json)
        if not payload_ok or type(p) ~= 'table' then plan_error() end
        if task.kind == 'reminder_complete' or task.kind == 'followup_complete' then
            if task.time_basis ~= 'none' or p.action_id ~= plan.action_id
                or p.spec_digest ~= state.digest then plan_error() end
        elseif task.time_basis ~= 'transport_recorded' or p.sent_at_ms ~= cjson.null then
            plan_error()
        end
    end
    if count ~= #plan.tasks or next(required) ~= nil then plan_error() end
    return plan
end

local function dormant_tasks(plan)
    local effects = {}
    for index, template in ipairs(plan.tasks) do
        local task = cjson.decode(cjson.encode(template))
        task.state, task.attempts, task.lease_token = 'not_started', 0, ''
        task.lease_until_ms, task.next_attempt_at_ms, task.result_code = 0, 0, ''
        effects[index] = task
    end
    return effects
end

local function validate_dormant(state)
    local plan = read_plan(state)
    if type(state.effects) ~= 'table' or #state.effects ~= #plan.tasks then plan_error() end
    local count = 0
    for index, task in pairs(state.effects) do
        count = count + 1
        local template = plan.tasks[index]
        if type(task) ~= 'table' or not template or task.state ~= 'not_started'
            or task.effect_id ~= template.effect_id or task.kind ~= template.kind
            or task.codec_version ~= template.codec_version or task.time_basis ~= template.time_basis
            or task.payload_json ~= template.payload_json or task.payload_digest ~= template.payload_digest then
            plan_error()
        end
    end
    if count ~= #plan.tasks then plan_error() end
    return plan
end

local function install_plan(state)
    if state.effects_version ~= nil then
        validate_dormant(state)
        return
    end
    if ARGV[8] and ARGV[8] ~= '' then
        state.effects_version, state.plan_json = 1, ARGV[8]
        state.plan_digest, state.plan_sha1 = ARGV[9], ARGV[10]
        state.effects = dormant_tasks(read_plan(state))
    elseif ARGV[11] == 'yes' then plan_error() end
end

local function activate_effects(state, source, at)
    if state.effects_version == nil then
        -- Transitional legacy senders still write directly. Never manufacture
        -- replayable tasks for those records merely from a sent conclusion.
        if source == 'owner' then
            state.confirmation_source, state.sent_recorded_at_ms = source, at
            state.delivered_at_ms = cjson.null
            state.effects_state, state.effects_review_reason = 'needs_review', 'actual_delivery_time_unknown'
        else state.effects_state = 'pending' end
        return
    end
    local effects = dormant_tasks(validate_dormant(state))
    local review = false
    for _, task in ipairs(effects) do
        task.state = 'pending'
        if task.time_basis == 'transport_recorded' then
            if source == 'owner' then
                task.state, task.result_code, task.time_basis = 'needs_review', 'actual_delivery_time_unknown', 'unknown'
                review = true
            else
                local p = cjson.decode(task.payload_json)
                p.sent_at_ms = at
                task.payload_json = cjson.encode(p)
                task.payload_digest = redis.sha1hex(task.payload_json)
            end
        end
    end
    state.effects, state.confirmation_source, state.sent_recorded_at_ms = effects, source, at
    state.delivered_at_ms = cjson.null
    state.effects_state = review and 'needs_review' or 'pending'
    state.effects_review_reason = review and 'actual_delivery_time_unknown' or nil
end
"""
