"""Sent-only source completion and private projection with permanent receipts."""
import hashlib
from datetime import datetime
from redis.exceptions import ConnectionError as RedisConnectionError, TimeoutError as RedisTimeoutError

from src.services.persistence.effects.source_scripts import PREFIX as RECEIPT
from src.services.persistence.effects.source import source_payload
from src.services.persistence.effects.store import EffectUnavailable, EffectNeedsReview, EffectIncomplete, EffectConflict
from .repository import key, PREFIX, canonical
from .codec import ENCODE

APPLY = RECEIPT + ENCODE + r'''
for i,wanted in pairs({[3]='hash',[4]='hash',[5]='hash',[6]='hash',[7]='zset',[8]='hash'}) do
    require_type(KEYS[i],wanted)
end
local state = decode(redis.call('HGET',KEYS[8],'state'))
if state and state.pending then return 'pending' end
local pid,step = string.match(spec.business_id,'^([0-9a-f]+):(%a+)$')
local p = decode(redis.call('HGET',KEYS[5],pid))
if not p then return 'missing' end
if p.status ~= 'active' then return finish('cancelled') end
local raw = redis.call('HGET',KEYS[3],spec.business_id)
local revision = redis.call('HGET',KEYS[4],spec.business_id)
if revision ~= spec.revision then return finish('superseded') end
local source = decode(raw)
if not source or redis.sha1hex(raw) ~= spec.source_digest or source.plan_id ~= pid
    or source.bot_id ~= spec.bot_id or tostring(p.user_id) ~= spec.target_id
    or source.content_revision ~= p.content_revision or source.payload ~= spec.payload
    or not p.steps[step] or p.steps[step].action_id ~= action_id then return 'inconsistent' end
if step == 'review' and (p.consent ~= 'granted' or source.authorization_revision ~= p.authorization_revision) then
    return finish('cancelled')
end
local note = decode(redis.call('HGET',KEYS[6],p.note_id))
if not note or note.user_id ~= p.user_id or note.category ~= 'companion'
    or note.visibility ~= 'private' or note.title ~= '考试计划:'..pid then return 'inconsistent' end
p.steps[step].status,p.steps[step].source_complete,p.steps[step].reason = 'finished',true,''
p.revision,p.updated_at_ms = p.revision+1,now
note.content = encode_plan({title=p.title,tasks=p.tasks,status=p.status,exam=p.exam_iso,
    reminder=p.remind_iso,consent=p.consent,review=p.review,steps=p.steps})
begin_effect()
redis.call('HSET',KEYS[5],pid,encode_plan(p))
redis.call('HSET',KEYS[6],p.note_id,cjson.encode(note))
redis.call('ZREM',KEYS[7],spec.target_id..':'..spec.business_id)
return finish('applied')
'''


def complete_effect(client, effect_id, spec):
    user = int(spec.target_id)
    binding = hashlib.sha256(canonical([effect_id,spec.encode(),source_payload(spec)]).encode()).hexdigest()
    keys = [f'mako:delivery:v1:effect-source:{effect_id}', f'mako:delivery:v1:{spec.action_id}',
            key('steps',user),key('source',user),key('plans',user),f'notes:{user}',PREFIX+'due',
            f'mako:memory:v1:control:{user}']
    try:
        result = client.eval(APPLY,len(keys),*keys,binding,effect_id,spec.action_id,spec.encode(),
                             source_payload(spec),'companion_complete',datetime.now().isoformat(),spec.digest)
        if isinstance(result,bytes):
            result = result.decode()
    except (RedisConnectionError,RedisTimeoutError,ConnectionError,TimeoutError) as exc:
        raise EffectUnavailable('companion effect outcome unknown') from exc
    except Exception as exc:
        raise EffectNeedsReview('companion source completion requires review') from exc
    if result == 'pending':
        raise EffectUnavailable('original control intent pending')
    if result == 'conflict':
        raise EffectConflict('source completion identity conflict')
    if result == 'incomplete':
        raise EffectIncomplete('source completion incomplete')
    if result not in {'applied','already_applied','superseded','cancelled','missing','inconsistent','wrong_action'}:
        raise EffectNeedsReview('invalid companion effect result')
    return result
