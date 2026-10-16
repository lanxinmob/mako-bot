"""Finite, self-scoped routing without model calls or adapter authority."""
import re
from dataclasses import dataclass
from .facts import fact, subject
from .runtime import for_storage


@dataclass(frozen=True)
class Command:
    operation: str
    memory_id: str = ''
    text: str = ''


def parse(text):
    text = text.strip().lstrip('/.')
    if text in {'关系记忆', '我的记忆', '茉子记得什么', 'memories'}:
        return Command('list')
    match = re.fullmatch(r'(解释记忆|纠正记忆|删除记忆|忘掉记忆|重新记住|explain-memory|correct-memory|forget-memory|relearn-memory)\s+(\S+)(?:\s+(.+))?', text)
    if match:
        operation = {'解释记忆': 'explain', '纠正记忆': 'correct', '删除记忆': 'forget',
                     '忘掉记忆': 'forget', '重新记住': 'relearn',
                     'explain-memory': 'explain', 'correct-memory': 'correct',
                     'forget-memory': 'forget', 'relearn-memory': 'relearn'}[match[1]]
        return Command(operation, match[2], match[3] or '')
    if text == '忘掉这件事' or text.casefold().rstrip('.!') == 'forget this':
        return Command('quoted_forget')
    if text in {'你为什么这样记我', '你为什么这样记我？', '以前喜欢，现在不喜欢了'}:
        return Command('choose')
    match = re.fullmatch(r'你为什么觉得我(?:喜欢|不喜欢|讨厌)(.+?)[？?]?', text)
    if match:
        return Command('why', text=match[1])
    match = re.fullmatch(r"Why do you think I (?:like|dislike|hate|don't like|do not like) (.+?)[?]?", text, re.I)
    if match:
        return Command('why', text=match[1])
    if (text.startswith('以前喜欢') or text.casefold().startswith('i used to like ')) and fact(text):
        return Command('change', text=text)
    return None


async def execute(ledger, user, command, source, *, admit=None):
    """Return text, frozen content view, and optional explanation ID."""
    if not await ledger.reconcile(user, admit=admit):
        return '本次未接纳，未修改记忆。', None, None
    view = for_storage(ledger.storage, [user])
    if not view.available and command.operation not in {'correct', 'forget', 'relearn'}:
        return '记忆控制暂时不可用，修改结果可能待确认；请稍后查询。', None, None
    operation, mid, text = command.operation, command.memory_id, command.text
    if operation == 'list':
        return ledger.format(user), view, None
    if operation == 'choose':
        return '请提供记忆 ID 和明确的新陈述。\n' + ledger.format(user), view, None
    if operation in {'why', 'change'}:
        if operation == 'change' and source.get('quoted'):
            return '引用不作为本人的新陈述，请明确提供 ID 和新陈述。', None, None
        topic = subject('preference', text) if operation == 'why' else fact(text)['subject_key']
        matches = [m for m in ledger.list(user) if m.status == 'active' and ledger.topic(m) == topic]
        if len(matches) != 1:
            return '无法唯一确定这条记忆，请选择 ID。\n' + ledger.format(user), view, None
        mid = matches[0].memory_id
        operation = 'explain' if operation == 'why' else 'correct'
    if operation == 'explain':
        return ledger.explain(user, mid), view, mid
    if operation in {'correct', 'relearn'} and not text:
        return '请提供 ID 和明确的新陈述。', None, None
    result = await ledger.mutate(user, operation, mid, text, source,
                                 expected_revision=view.states.get(user, {}).get('revision'), admit=admit)
    status = result['status']
    messages = {'not_found': '没有可操作的本人记录。', 'wrong_topic': '类型或主题不同，未修改。请另行明确陈述新事实，再遗忘旧条目。',
                'rejected': '这条记录当前不能这样修改；已完成承诺不会重新变成待跟进。',
                'conflict': '记忆已更新，请刷新后使用当前 ID。', 'busy': '修改结果待确认，请稍后查询。',
                'already_processed': '这条消息已处理，请查询当前状态。', 'blocked': '该主题已遗忘；只有“重新记住 ID 新陈述”可以重新授权。'}
    if status == 'access_rejected':
        return '本次未接纳，未修改记忆。', None, None
    if status == 'forgotten':
        return ('已遗忘：正文、来源片段和精确镜像已清空，后续跟进停止。历史聊天仍保留；'
                '已进入发送的消息可能已经包含旧信息，未确认结果不能撤回。'), None, None
    if status not in {'correct', 'relearn', 'replace', 'create'}:
        return messages.get(status, '修改结果待确认，请查询当前状态。'), None, None
    updated = for_storage(ledger.storage, [user])
    new_id = result['memory_id']
    body = ledger.explain(user, new_id)
    suffix = '\n承诺原日期未变，完成状态不会重新激活。' if any(m.memory_id == new_id and m.memory_type == 'promise' for m in ledger.list(user)) else ''
    return f'已更新；新 ID {new_id}，原 ID {mid}。\n{body}\n账本优先；旧画像暂停使用。{suffix}', updated, None
