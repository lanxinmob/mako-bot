"""Current self projections distinguish business, consent, transport and effects."""
from dataclasses import dataclass

from src.services.delivery.state import DeliveryStore
from src.services.memory.ledger.runtime import for_storage, critical
from .commands import EXAMPLE
from .workflow import display_time

STATUS = {'active':'进行中','completed':'已完成','cancelled':'已取消','closed':'已关闭','forgotten':'已遗忘'}
BUSINESS = {'scheduled':'已安排','blocked':'暂停','expired':'已过期','finished':'步骤已完成','cancelled':'已停止'}
TRANSPORT = {'queued':'排队中','sending':'发送中','sent':'已确认发送','unknown':'确认未知',
             'rejected_before_send':'发送前拒绝','cancelled':'已停止'}
CONSENT = {'none':'未授权','granted':'已同意一次邀请','revoked':'已撤销'}
REASONS = {'permission':'资格已撤销', 'memory_changed':'记忆版本已变化',
           'reminder_unconfirmed':'考前提醒未确认或补记未完成', 'storage':'存储待确认',
           'bot_unavailable':'机器人未连接'}
RESULTS = {'capacity':'已有一个进行中的计划，请先查看或结束。',
    'conflict':'计划已更新，本次未覆盖；请重新查看。', 'not_found':'没有可操作的本人计划。',
    'invalid_time':'时间不满足未来、考试前后或截止条件，本次未保存。',
    'transport_started':'原消息已进入发送或结果未知，不能重建发送；可查询、取消或直接提交回顾。',
    'too_early':'考试尚未开始，不能提交回顾。', 'invalid_task':'完成序号超出当前任务范围。',
    'ended':'计划已结束，不能修改或授权。', 'rejected':'请本人直接发送完整纯文本命令，不接受第三方引用。',
    'access_rejected':'访问资格已撤销。', 'busy':'已有操作待确认，请稍后查询。',
    'unconfirmed':'操作结果待确认，请稍后查询。', 'already_processed':'该事件已处理，不会重新执行。'}


def step_projection(repo, item, step):
    meta = item['steps'].get(step)
    if not meta:
        return dict(business='未安排',transport='尚未开始',effects='尚未开始',reason='')
    state = DeliveryStore(repo.client).inspect(meta['action_id'])
    effect = '尚未开始'
    if state.state == 'sent':
        effect = '已完成' if meta['source_complete'] else '待补记确认'
        if not meta['source_complete']:
            from src.services.delivery.effects.store import EffectStore
            try:
                receipt = EffectStore(repo.client).inspect(meta['action_id'])
                if receipt and all(t.state in {'complete','skipped'} for t in receipt.tasks):
                    effect = '已停止正文补记（来源已失效）'
                elif receipt and any(t.state == 'needs_review' for t in receipt.tasks):
                    effect = '待核对'
            except Exception:
                effect = '待核对'
    elif state.state in {'unknown','sending'}:
        effect = '待核对'
    return dict(business=meta['status'],transport=state.state or '尚未开始',effects=effect,
                reason=REASONS.get(meta.get('reason'),meta.get('reason','')),action_id=meta['action_id'])


def project(repo, item):
    forgotten = item['status'] == 'forgotten'
    return dict(plan_id=item['plan_id'],user_id=item['user_id'],revision=item['revision'],status=item['status'],
        title='' if forgotten else item['title'],tasks=[] if forgotten else item['tasks'],
        exam='' if forgotten else item['exam_iso'],reminder_time='' if forgotten else item['remind_iso'],
        consent=item['consent'],review_time=display_time(item['review_ms']) if item.get('review_ms') and not forgotten else '',
        review=None if forgotten else item['review'],reminder=step_projection(repo,item,'reminder'),
        invitation=step_projection(repo,item,'review'))


def format_plan(item):
    lines = [f"计划 {item['plan_id']}｜版本 {item['revision']}｜{STATUS[item['status']]}",
             f"回顾授权：{CONSENT[item['consent']]}" ]
    if item['status'] != 'forgotten':
        lines += [item['title'],f"考试：{item['exam']}（北京时间）",f"提醒：{item['reminder_time']}（北京时间）"]
        lines += [f'{i+1}. {task}' for i,task in enumerate(item['tasks'])]
        if item['review_time']:
            lines.append('回顾：'+item['review_time']+'（北京时间）')
        if item['review']:
            review = item['review']
            lines += [f"完成 {len(review['completed'])}/{len(item['tasks'])} 项；序号：{review['completed'] or '无'}",
                      '本人感受：'+review['feeling'],'下次：'+review['next']]
    else:
        lines.append('正文、来源及精确关联笔记已清空；旧发送与历史审计仍保留。')
    for label,step in [('提醒',item['reminder']),('回顾邀请',item['invitation'])]:
        lines.append(f"{label}：{BUSINESS.get(step['business'],step['business'])}｜主发送 {TRANSPORT.get(step['transport'],step['transport'])}｜补记 {step['effects']}"+
                     (f"｜暂停原因 {step['reason']}" if step['reason'] else ''))
        if step['transport'] in {'unknown','sending'}:
            lines.append('确认未知或发送中，可能已发送；不会自动重发。')
    if item['status'] == 'active':
        pid = item['plan_id']
        lines.append(f'同意回顾 {pid} YYYY-MM-DD HH:MM；撤销回顾 {pid}；取消计划 {pid}')
    lines.append(f"查看计划 {item['plan_id']}；忘掉计划 {item['plan_id']}")
    lines.append('计划独立保存；停止提醒用取消计划，清除计划用忘掉计划；不影响其他关系记忆。')
    return '\n'.join(lines)


@dataclass
class ReplyView:
    repo: object
    user: int
    revisions: dict
    memory: object

    def current(self):
        try:
            return self.memory.current() and all(
                (self.repo.get(self.user,pid) or {}).get('revision') == rev for pid,rev in self.revisions.items())
        except Exception:
            return False

    async def send(self, sender, *, admit=None):
        async with critical():
            if (admit is not None and not admit()) or not self.current():
                return False
        return await sender()


def reply(service, user, command, result, bot_id):
    repo = service.repo
    memory = for_storage(service.storage,[user])
    if not memory.available:
        raise RuntimeError('plan control unavailable')
    plans = [p for p in repo.list(user) if p['bot_id'] == bot_id]
    pid = result.get('plan_id') or command.plan_id
    if command.operation != 'list':
        plans = [p for p in plans if p['plan_id'] == pid]
    plans = plans[:30]
    projected = [project(repo,p) for p in plans]
    code = result['status']
    prefix = RESULTS.get(code,'原事件已处理，当前状态如下。' if result.get('duplicate') else '')
    text = '\n\n'.join([prefix,*map(format_plan,projected)] if projected else
                         [prefix or ('暂无本人计划。\n'+EXAMPLE if command.operation == 'list' else '没有可操作的本人计划。')])
    return text,ReplyView(repo,user,{p['plan_id']:p['revision'] for p in plans},memory)
