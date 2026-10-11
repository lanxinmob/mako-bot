"""Quiet expiry and persistent blocked reasons; unknown transport stays unknown."""
import json
from .repository import key, PREFIX, CompanionUnavailable
from .codec import ENCODE

UPDATE = ENCODE + r'''
local wanted = {'hash','hash','zset','hash','hash'}
for i, kind in ipairs(wanted) do
    local actual = redis.call('TYPE',KEYS[i]).ok
    if actual ~= 'none' and actual ~= kind then error('invalid companion lifecycle key') end
end
local control = redis.call('HGET',KEYS[4],'state')
if control and cjson.decode(control).pending then return 'pending' end
local pid,user,expected,step,reason = unpack(ARGV)
local raw = redis.call('HGET',KEYS[1],pid)
if not raw or raw ~= expected then return 'changed' end
local p = cjson.decode(raw)
if p.status ~= 'active' then return 'terminal' end
local note_raw = redis.call('HGET',KEYS[5],p.note_id)
local note = note_raw and cjson.decode(note_raw) or nil
local linked = note and note.user_id == p.user_id and note.category == 'companion'
    and note.visibility == 'private' and note.title == '考试计划:'..pid
local tm = redis.call('TIME'); local now = tonumber(tm[1])*1000+math.floor(tonumber(tm[2])/1000)
local changed = false
if now >= p.exam_ms+604800000 then
    if p.consent == 'granted' then p.authorization_revision=p.authorization_revision+1 end
    p.status,p.consent = 'closed','revoked'
    for _,s in ipairs({'reminder','review'}) do
        if p.steps[s] and p.steps[s].status ~= 'finished' then p.steps[s].status='cancelled' end
        redis.call('HDEL',KEYS[2],pid..':'..s)
        redis.call('ZREM',KEYS[3],user..':'..pid..':'..s)
    end
    changed=true
elseif step ~= '' and p.steps[step] and p.steps[step].status ~= 'finished' then
    local at = step == 'reminder' and p.remind_ms or p.review_ms
    local until_ms = math.min(at+1800000,p.exam_ms+(step=='review' and 604800000 or 0))
    local status = now >= until_ms and 'expired' or (reason=='' and 'scheduled' or 'blocked')
    if p.steps[step].status ~= status or p.steps[step].reason ~= reason then
        p.steps[step].status,p.steps[step].reason=status,reason; changed=true
    end
    if status == 'expired' then redis.call('ZREM',KEYS[3],user..':'..pid..':'..step) end
end
if changed then
    p.revision,p.updated_at_ms=p.revision+1,now
    redis.call('HSET',KEYS[1],pid,encode_plan(p))
    if linked then
        note.content=encode_plan({title=p.title,tasks=p.tasks,status=p.status,exam=p.exam_iso,
            reminder=p.remind_iso,consent=p.consent,review=p.review,steps=p.steps})
        redis.call('HSET',KEYS[5],p.note_id,cjson.encode(note))
    end
end
return changed and 'updated' or 'unchanged'
'''


def update(repo, user, pid, *, step='', reason=''):
    raw = repo.raw(user, pid)
    if not raw:
        return 'missing'
    try:
        return repo.client.eval(UPDATE, 5, key('plans',user), key('source',user), PREFIX+'due',
                                f'mako:memory:v1:control:{user}',f'notes:{user}', pid,str(user),raw,step,reason)
    except Exception as exc:
        raise CompanionUnavailable('quiet expiry outcome unavailable') from exc
