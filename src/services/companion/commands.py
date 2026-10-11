"""A finite command grammar; malformed control commands still block chat."""
from dataclasses import dataclass, field
from datetime import datetime
import re
from zoneinfo import ZoneInfo

ZONE = ZoneInfo('Asia/Shanghai')
PREFIXES = ('创建考试计划', '我的考试计划', '查看计划', '修改计划', '同意回顾',
            '撤销回顾', '提交回顾', '取消计划', '忘掉计划')
EXAMPLE = ('创建考试计划 数学期中 | 考试=2026-10-20 09:00 | '
           '提醒=2026-10-19 20:00 | 任务=复习第三章；完成一套真题')


@dataclass(frozen=True)
class Command:
    operation: str
    plan_id: str = ''
    fields: dict = field(default_factory=dict)


def invoked(text):
    value = text.strip().removeprefix('/')
    return any(value == p or value.startswith(p + ' ') for p in PREFIXES)


def plain(value, limit):
    value = value.strip()
    if (not 1 <= len(value) <= limit or re.search(r'[|；\r\n]|\[CQ:|https?://', value, re.I)
            or re.search(r'(?:api[_ -]?key|token|password|密码)\s*[:=]|sk-[\w-]{12,}', value, re.I)):
        raise ValueError('请使用限长纯文本；不接受保留分隔符、换行、媒体链接或凭据。')
    return value


def instant(text):
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}', text):
        raise ValueError('时间须为 YYYY-MM-DD HH:MM，北京时间。')
    try:
        return int(datetime.strptime(text, '%Y-%m-%d %H:%M').replace(tzinfo=ZONE).timestamp() * 1000)
    except ValueError as exc:
        raise ValueError('日期或时间无效。') from exc


def fields(text, allowed, required=()):
    data = {}
    for part in text.split('|'):
        key, sep, value = part.strip().partition('=')
        if not sep or key not in allowed or key in data or not value.strip():
            raise ValueError('字段缺失、重复或未知，请按完整格式发送。')
        data[key] = value.strip()
    if not set(required) <= data.keys():
        raise ValueError('请提供全部必填字段。')
    result = {}
    for key, value in data.items():
        if key in {'考试', '提醒'}:
            result['exam_ms' if key == '考试' else 'remind_ms'] = instant(value)
        elif key == '任务':
            tasks = value.split('；')
            if not 1 <= len(tasks) <= 3:
                raise ValueError('请提供 1–3 个任务。')
            result['tasks'] = [plain(t, 100) for t in tasks]
        elif key == '名称':
            result['title'] = plain(value, 40)
        elif key == '完成':
            if value == '无':
                result['completed'] = []
            elif re.fullmatch(r'[1-3](?:,[1-3])*', value):
                result['completed'] = sorted(set(map(int, value.split(','))))
            else:
                raise ValueError('完成只接受任务序号，如 1,2 或 无。')
        else:
            result['feeling' if key == '感受' else 'next'] = plain(value, 200)
    return result


def parse(text):
    value = text.strip().removeprefix('/')
    if not invoked(text):
        return None
    if '\n' in value or '\r' in value or '[CQ:' in value:
        raise ValueError('请发送一条完整纯文本命令。')
    if value == '我的考试计划':
        return Command('list')
    name, _, rest = value.partition(' ')
    rest = rest.strip()
    if name == '创建考试计划':
        title, sep, tail = rest.partition('|')
        if not sep:
            raise ValueError(EXAMPLE)
        return Command('create', fields=dict(title=plain(title, 40),
            **fields(tail, {'考试', '提醒', '任务'}, {'考试', '提醒', '任务'})))
    pid, _, tail = rest.partition(' ')
    if not re.fullmatch(r'[0-9a-f]{12}', pid):
        raise ValueError('请提供回执中的本人计划 ID。')
    if name in {'查看计划', '撤销回顾', '取消计划', '忘掉计划'}:
        if tail:
            raise ValueError('该命令只接受一个计划 ID。')
        return Command({'查看计划': 'view', '撤销回顾': 'revoke',
                        '取消计划': 'cancel', '忘掉计划': 'forget'}[name], pid)
    if name == '同意回顾':
        return Command('consent', pid, {'review_ms': instant(tail.strip())})
    if name == '修改计划':
        return Command('edit', pid, fields(tail, {'名称', '考试', '提醒', '任务'}))
    if name == '提交回顾':
        return Command('submit', pid, fields(tail, {'完成', '感受', '下次'}, {'完成', '感受', '下次'}))
    raise ValueError('请使用完整的考试计划命令。')
