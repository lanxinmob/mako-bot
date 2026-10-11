"""Business transitions share Redis TIME and one atomic commit with C2 control."""
from .operations import PREFIX

SCRIPT = PREFIX + r'''
if operation == 'create' then
    local candidate = intent.plan
    if candidate.exam_ms <= now or candidate.exam_ms > now+7776000000 or candidate.remind_ms < now+300000
        or candidate.remind_ms > candidate.exam_ms-300000 then return complete({status='invalid_time',plan_id=pid}) end
end
if operation == 'create' then
    if raw then return complete({status='conflict',plan_id=pid}) end
    for _, item in ipairs(redis.call('HVALS',KEYS[1])) do
        local prior = decode(item)
        if prior.status == 'active' and now < prior.exam_ms + 604800000 then
            return complete({status='capacity',plan_id=prior.plan_id})
        end
    end
    plan = intent.plan
elseif not plan then return complete({status='not_found'})
elseif plan.status == 'forgotten' then return complete({status='forgotten',plan_id=pid,revision=plan.revision})
elseif operation == 'forget' then
    stop('reminder','cancelled'); stop('review','cancelled')
    plan.title,plan.tasks,plan.review = '',{},cjson.null
    plan.exam_ms,plan.remind_ms,plan.review_ms = cjson.null,cjson.null,cjson.null
    plan.exam_iso,plan.remind_iso = '',''
    plan.source,plan.consent_source = {},{}
    plan.consent,plan.status = 'revoked','forgotten'
    redis.call('HDEL',KEYS[2],pid..':reminder',pid..':review')
    redis.call('HDEL',KEYS[6],plan.note_id)
    control.revision = control.revision + 1
    local cutoff = tostring(control.cutoff_ns)
    if #intent.cutoff_ns > #cutoff or (#intent.cutoff_ns == #cutoff and intent.cutoff_ns > cutoff) then
        control.cutoff_ns = intent.cutoff_ns
    end
    control.controlled = true
elseif operation == 'cancel' then
    if plan.status ~= 'active' then return complete({status=plan.status,plan_id=pid,revision=plan.revision}) end
    stop('reminder','cancelled'); stop('review','cancelled')
    plan.consent,plan.status = 'revoked','cancelled'
elseif plan.status ~= 'active' then return complete({status='ended',plan_id=pid,revision=plan.revision})
elseif now >= plan.exam_ms + 604800000 then
    stop('reminder','cancelled'); stop('review','cancelled')
    plan.status,plan.consent = 'closed','revoked'
elseif operation == 'edit' then
    if not unstarted(KEYS[8]) then return complete({status='transport_started',plan_id=pid}) end
    if intent.no_change then return complete({status='unchanged',plan_id=pid,revision=plan.revision}) end
    local candidate = intent.plan
    if candidate.exam_ms <= now or candidate.exam_ms > now+7776000000 or candidate.remind_ms < now+300000
        or candidate.remind_ms > candidate.exam_ms-300000 then return complete({status='invalid_time',plan_id=pid}) end
    stop('reminder','cancelled'); stop('review','cancelled')
    plan = intent.plan
elseif operation == 'consent' then
    if not unstarted(KEYS[9]) then return complete({status='transport_started',plan_id=pid}) end
    if plan.consent == 'granted' and plan.review_ms == intent.review_ms then
        return complete({status='unchanged',plan_id=pid,revision=plan.revision})
    end
    if intent.review_ms <= plan.exam_ms or intent.review_ms >= plan.exam_ms+604800000
        or intent.review_ms < now+300000 then return complete({status='invalid_time',plan_id=pid}) end
    stop('review','cancelled')
    plan.consent,plan.review_ms = 'granted',intent.review_ms
    plan.authorization_revision = plan.authorization_revision + 1
    plan.consent_source = intent.source
elseif operation == 'revoke' then
    if plan.consent ~= 'granted' then return complete({status='unchanged',plan_id=pid,revision=plan.revision}) end
    stop('review','cancelled')
    plan.consent = 'revoked'
    plan.authorization_revision = plan.authorization_revision+1
elseif operation == 'submit' then
    if now < plan.exam_ms then return complete({status='too_early',plan_id=pid}) end
    for _, index in ipairs(intent.review.completed) do
        if index > #plan.tasks then return complete({status='invalid_task',plan_id=pid}) end
    end
    stop('reminder','cancelled'); stop('review','cancelled')
    plan.review,plan.status = intent.review,'completed'
else return complete({status='rejected',plan_id=pid}) end
if operation == 'create' or operation == 'edit' or operation == 'consent' then
    for step, frozen in pairs(intent.frozen) do
        if operation ~= 'consent' or plan.status == 'active' then
            local sid = pid..':'..step
            redis.call('HSET',KEYS[2],sid,frozen.raw)
            redis.call('HSET',KEYS[3],sid,frozen.revision)
            redis.call('ZADD',KEYS[4],frozen.at,intent.user_id..':'..sid)
            plan.steps[step] = {status='scheduled',reason='',action_id=frozen.action_id,
                revision=frozen.revision,source_complete=false}
        end
    end
end
if operation ~= 'create' then plan.revision = plan.revision+1 end
if (operation == 'cancel' or operation == 'forget' or plan.status == 'closed') and original_consent == 'granted' then
    plan.authorization_revision = plan.authorization_revision+1
end
plan.updated_at_ms = now
redis.call('HSET',KEYS[1],pid,encode_plan(plan))
if plan.status ~= 'forgotten' then
    local note = intent.note
    note.content = encode_plan({title=plan.title,tasks=plan.tasks,status=plan.status,
        exam=plan.exam_iso,reminder=plan.remind_iso,consent=plan.consent,review=plan.review,steps=plan.steps})
    redis.call('HSET',KEYS[6],plan.note_id,cjson.encode(note))
end
return complete({status=plan.status,plan_id=pid,revision=plan.revision})
'''
