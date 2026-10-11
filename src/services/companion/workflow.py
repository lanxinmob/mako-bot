"""Self-only commands build immutable intents; Redis owns admission and time."""
from copy import deepcopy
from datetime import datetime
import json
import time
import uuid

from src.models.schemas import NoteRecord
from src.services.memory.ledger.service import identity
from src.services.memory.ledger.runtime import critical, confirmed_thread
from src.services.persistence.companion.repository import CompanionRepository, canonical
from src.services.persistence.companion.models import spec_for
from .commands import ZONE


def display_time(ms):
    return datetime.fromtimestamp(ms/1000, ZONE).isoformat(timespec='minutes')


def freeze(plan, step, memory_revision):
    pid, user = plan['plan_id'], plan['user_id']
    when = plan['remind_ms'] if step == 'reminder' else plan['review_ms']
    until = min(when+1800000, plan['exam_ms'] + (604800000 if step == 'review' else 0))
    tasks = '\n'.join(f'{i+1}. {t}' for i, t in enumerate(plan['tasks']))
    payload = (f"考试提醒｜{plan['title']}｜计划 {pid}\n考试：{plan['exam_iso']}（北京时间）\n{tasks}\n"
               f'查看计划 {pid}；取消计划 {pid}' if step == 'reminder' else
               f"回顾邀请｜{plan['title']}｜计划 {pid}\n这是你同意的一次回顾邀请，不回复不会追问。\n"
               f'{tasks}\n提交回顾 {pid} 完成=无 | 感受=你的感受 | 下次=下一次想改变的事\n撤销回顾 {pid}')
    revision = uuid.uuid4().hex
    raw = canonical(dict(schema_version=1, plan_id=pid, user_id=user, bot_id=plan['bot_id'], step=step,
        revision=revision, content_revision=plan['content_revision'], memory_revision=memory_revision,
        authorization_revision=plan['authorization_revision'] if step == 'review' else 0,
        at_ms=when, until_ms=until, payload=payload))
    spec = spec_for(user, pid+':'+step, raw, revision)
    return dict(raw=raw, revision=revision, at=when, action_id=spec.action_id)


class CompanionService:
    def __init__(self, storage):
        self.storage = storage
        self.repo = CompanionRepository(storage.backend)

    async def reconcile(self, user, *, admit=None):
        async with critical():
            if admit is not None and not admit():
                return False
            await confirmed_thread(self.repo.reconcile, user)
            return True

    async def execute(self, user, command, source, *, admit=None):
        if source.get('scene') != 'private' or source.get('quoted'):
            return dict(status='rejected')
        event = identity(user, source, 'companion')
        async with critical():
            if admit is not None and not admit():
                return dict(status='access_rejected')
            await confirmed_thread(self.repo.reconcile, user)
            if command.operation in {'list', 'view'}:
                return dict(status='query', plan_id=command.plan_id)
            return await confirmed_thread(self._execute, user, command, source, event)

    def _execute(self, user, command, source, event):
        recovered = self.repo.recover(user, event)
        if recovered:
            return dict(recovered, duplicate=True)
        control = self.repo.state(user)
        now = self.repo.now()
        operation, fields = command.operation, command.fields
        pid = command.plan_id or uuid.uuid4().hex[:12]
        raw = self.repo.raw(user, pid)
        old = json.loads(raw) if raw else None
        if operation != 'create' and (not old or old['bot_id'] != source['bot_id']):
            return dict(status='not_found')
        source = {k: source.get(k) for k in ('bot_id','user_id','message_id','scene','occurred_at','received_at')}
        if operation == 'create':
            plan = dict(schema_version=1, plan_id=pid, user_id=user, bot_id=source['bot_id'],
                status='active', consent='none', revision=1, content_revision=1, authorization_revision=0,
                title=fields['title'], tasks=fields['tasks'], exam_ms=fields['exam_ms'], remind_ms=fields['remind_ms'],
                created_at_ms=now, updated_at_ms=now, source=source, consent_source={}, review=None,
                review_ms=None, steps={}, note_id='exam-'+pid)
        else:
            plan = deepcopy(old)
        frozen = {}
        no_change = False
        if operation == 'edit':
            no_change = all(plan.get(k) == v for k, v in fields.items())
            plan.update(fields)
            if not no_change:
                plan['content_revision'] += 1
                plan['authorization_revision'] += 1
                plan.update(consent='revoked', consent_source={}, review_ms=None, source=source)
        if operation in {'create', 'edit'} and plan['status'] == 'active':
            plan['exam_iso'], plan['remind_iso'] = display_time(plan['exam_ms']), display_time(plan['remind_ms'])
            frozen['reminder'] = freeze(plan, 'reminder', control['revision'])
        if operation == 'consent' and plan['status'] == 'active':
            preview = deepcopy(plan)
            preview['review_ms'] = fields['review_ms']
            preview['authorization_revision'] += 1
            frozen['review'] = freeze(preview, 'review', control['revision'])
        note = NoteRecord(note_id=plan['note_id'], user_id=user, title='考试计划:'+pid,
                          content='', category='companion', visibility='private')
        intent = dict(user_id=str(user), plan_id=pid, operation=operation, expected=raw or False,
            memory_revision=control['revision'], plan=plan, frozen=frozen,
            note=note.model_dump(mode='json'), cutoff_ns=str(time.time_ns()), source=source,
            review_ms=fields.get('review_ms'), review={k:fields[k] for k in ('completed','feeling','next') if k in fields},
            no_change=no_change)
        return self.repo.apply(user, event, intent)
