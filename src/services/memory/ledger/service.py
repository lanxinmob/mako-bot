"""Deterministic records and user operations; callers supply trusted identities."""
import hashlib
import json
import time
import uuid
from datetime import datetime

from src.models.schemas import RelationshipMemory, NoteRecord
from src.services.persistence.ledger import LedgerRepository, LedgerUnavailable
from .facts import fact, subject
from .runtime import critical, confirmed_thread

LABELS = {'preference': '用户偏好', 'taboo': '用户禁忌', 'event': '关系事件', 'promise': '跟进承诺'}
STATUSES = {'active': '有效', 'done': '已完成', 'replaced': '已替换', 'forgotten': '已遗忘'}


def identity(user_id, source, suffix=''):
    if not source.get('bot_id') or not source.get('message_id') or source.get('user_id') != user_id:
        raise ValueError('缺少可信的本人消息标识，请重新发送命令。')
    value = json.dumps([source['bot_id'], user_id, str(source['message_id']), suffix])
    return hashlib.sha256(value.encode()).hexdigest()


class LedgerService:
    def __init__(self, storage, *, allow_memory=False):
        self.storage = storage
        self.repo = LedgerRepository(storage.backend, allow_memory=allow_memory)

    def list(self, user_id):
        self.repo.state(user_id)
        return [RelationshipMemory.model_validate_json(raw) for raw in self.repo.rows(user_id).values()]

    def explain(self, user_id, memory_id):
        item = next((m for m in self.list(user_id) if m.memory_id == memory_id), None)
        if not item:
            return '没有可操作的本人记录。'
        if item.status == 'forgotten':
            return f'{item.memory_id}｜已遗忘；正文和来源片段已清空。'
        basis = ('未保存原始来源，无法确认原话和发生时间。' if item.evidence_kind == 'legacy_unknown' else
                 f"依据：{item.source_excerpt}\n场景：{item.source_ref.get('scene', '未知')}\n"
                 f"发生时间：{item.source_ref.get('occurred_at') or '未知'}\n接收时间：{item.source_ref.get('received_at') or '未知'}")
        due = f'\n承诺日期：{item.due_at.isoformat()}（更正正文不改变日期）' if item.due_at else ''
        chain = f'\n替换：{item.replaces or "无"}；被替换为：{item.replaced_by or "无"}；版本：{item.revision}'
        return f'{item.memory_id}｜{LABELS[item.memory_type]}｜{STATUSES[item.status]}｜{item.content}\n{basis}{due}{chain}\n规则置信值 {item.confidence}，未经准确率校准。'

    def format(self, user_id):
        rows = self.list(user_id)
        lines = ['你的关系记忆账本：']
        for m in sorted(rows, key=lambda m: (m.status != 'active', -m.created_at.timestamp()))[:30]:
            lines.append(f'{m.memory_id}｜{LABELS[m.memory_type]}｜{STATUSES[m.status]}｜{m.content if m.status != "forgotten" else "正文已清空"}｜'
                         + ('来源未知' if m.evidence_kind == 'legacy_unknown' else '来源明确'))
        if not rows:
            lines.append('暂无条目。')
        elif len(rows) > 30:
            lines.append(f'共 {len(rows)} 条，本次列出 30 条，有效条目优先；已知 ID 可直接解释查看状态。')
        state = self.repo.state(user_id)
        lines.append('账本优先；旧画像暂停使用。' if state['controlled'] else '尚未进入账本优先模式。')
        lines.append('解释记忆 ID；纠正记忆 ID 新陈述；忘掉记忆 ID。遗忘不物理删除历史聊天。')
        return '\n'.join(lines)

    async def reconcile(self, user_id, *, admit=None):
        async with critical():
            if admit is not None and not admit():
                return False
            await confirmed_thread(self.repo.reconcile, user_id)
            return True

    async def mutate(self, user_id, operation, memory_id, text, source, *, due_at=None, expected_revision=None, admit=None):
        event = identity(user_id, source, 'auto:' + (fact(text) or {}).get('subject_key', '') if operation == 'auto' else '')
        async with critical():
            if admit is not None and not admit():
                return dict(status='access_rejected')
            return await confirmed_thread(self._mutate, user_id, operation, memory_id, text, source, event, due_at, expected_revision)

    def _mutate(self, user_id, operation, memory_id, text, source, event, due_at, expected_revision):
        recovered = self.repo.recover(user_id, event)
        if recovered:
            return recovered
        state = self.repo.state(user_id)
        def receipt(status, mid=None):
            return self.repo.apply(user_id, event, dict(expected_revision=state['revision'], expected={}, expected_notes={},
                                                      no_change=True, status=status, memory_id=mid))
        if expected_revision is not None and state['revision'] != expected_revision:
            return receipt('conflict')
        raw_rows = self.repo.rows(user_id)
        rows = {k: RelationshipMemory.model_validate_json(v) for k, v in raw_rows.items()}
        target = rows.get(memory_id) if memory_id else None
        parsed = fact(text, target.memory_type if target else None)
        if operation == 'auto':
            if not parsed or source.get('quoted'):
                return dict(status='ignored')
            if source.get('received_ns') and int(source['received_ns']) <= int(state['cutoff_ns']):
                return receipt('ignored')
            candidates = [m for m in rows.values() if m.status == 'active' and self.topic(m) == parsed['subject_key']]
            if self.repo.blocked(user_id, parsed['subject_key']):
                return receipt('blocked')
            if len(candidates) > 1:
                return dict(status='ambiguous')
            target = candidates[0] if candidates else None
            if target and target.content == parsed['content']:
                return receipt('unchanged', target.memory_id)
            operation = 'replace' if target else 'create'
        elif not target:
            return dict(status='not_found')
        if operation == 'forget' and target.status == 'forgotten':
            return receipt('forgotten', target.memory_id)
        if operation == 'relearn' and (target.status != 'forgotten' or target.memory_type == 'promise'):
            return dict(status='rejected')
        if operation in {'replace', 'correct', 'relearn'}:
            if not parsed or parsed['subject_key'] != self.topic(target):
                return dict(status='wrong_topic')
            if operation != 'relearn' and target.status not in {'active', 'done'}:
                return dict(status='rejected')
            if operation == 'relearn' and (not self.repo.blocked(user_id, parsed['subject_key']) or
                    any(m.status == 'active' and self.topic(m) == parsed['subject_key'] for m in rows.values())):
                return dict(status='rejected')
        if operation == 'forget':
            topic = self.topic(target)
        elif parsed:
            topic = parsed['subject_key']
        else:
            return dict(status='ignored')
        if operation != 'relearn' and operation != 'forget' and self.repo.blocked(user_id, topic):
            return dict(status='blocked')
        plan = dict(user_id=str(user_id), expected_revision=state['revision'], expected={}, records={},
                    expected_notes={}, notes={}, delete_notes=[], cancel=[], due={}, blocked={},
                    controlled=operation != 'create', cutoff_ns=str(time.time_ns()), status=operation, memory_id=memory_id)
        note_rows = self.repo.notes(user_id)
        def write(memory):
            mid = memory.memory_id
            plan['expected'][mid] = raw_rows.get(mid, False)
            plan['records'][mid] = memory.model_dump_json()
        def remove_mirrors(memory):
            title = LABELS[memory.memory_type] + ':' + memory.memory_id
            for nid, raw in note_rows.items():
                note = NoteRecord.model_validate_json(raw)
                if note.user_id == user_id and note.category == 'relationship' and note.title == title:
                    plan['expected_notes'][nid] = raw
                    plan['delete_notes'].append(nid)
        if operation == 'forget':
            for memory in rows.values():
                if self.topic(memory) != topic:
                    continue
                remove_mirrors(memory)
                plan['cancel'].append(memory.memory_id)
                memory = memory.model_copy(update=dict(content='', source_ref={}, source_excerpt='', status='forgotten',
                    subject_key=topic, revision=memory.revision + 1, control_revision=state['revision'] + 1,
                    mirror_note_id=None, due_at=None, updated_at=datetime.now()))
                write(memory)
            plan['blocked'][topic] = True
            plan['status'] = 'forgotten'
        else:
            status = 'done' if target and target.status == 'done' else 'active'
            item = RelationshipMemory(memory_id=uuid.uuid4().hex[:12], user_id=user_id, **parsed,
                revision=1, source='chat', source_ref={k: source.get(k) for k in
                    ('bot_id', 'message_id', 'user_id', 'scene', 'occurred_at', 'received_at')}, source_excerpt=text[:160],
                evidence_kind='explicit' if operation == 'create' else 'user_correction',
                replaces=target.memory_id if target else None, status=status,
                due_at=target.due_at if target else due_at, control_revision=state['revision'] + 1,
                mirror_note_id=uuid.uuid4().hex[:10])
            if target:
                remove_mirrors(target)
                plan['cancel'].append(target.memory_id)
                write(target.model_copy(update=dict(status='forgotten' if operation == 'relearn' else 'replaced', replaced_by=item.memory_id,
                    revision=target.revision + 1, subject_key=topic, mirror_note_id=None, updated_at=datetime.now())))
            write(item)
            note = NoteRecord(note_id=item.mirror_note_id, user_id=user_id,
                              title=LABELS[item.memory_type] + ':' + item.memory_id, content=item.content, category='relationship')
            plan['expected_notes'][note.note_id] = False
            plan['notes'][note.note_id] = note.model_dump_json()
            if item.status == 'active' and item.due_at:
                plan['due'][item.memory_id] = dict(at=item.due_at.timestamp(), revision=uuid.uuid4().hex)
            plan['memory_id'] = item.memory_id
            if operation == 'relearn':
                plan['blocked'][topic] = False
        return self.repo.apply(user_id, event, plan)

    @staticmethod
    def topic(memory):
        return memory.subject_key or (fact(memory.content, memory.memory_type) or {}).get('subject_key') or subject(memory.memory_type, memory.content)
