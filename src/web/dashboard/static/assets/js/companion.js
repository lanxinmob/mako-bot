// Read-only exam states. Every user string is inserted as textContent.
import { state } from './state.js';

export function renderCompanion(h) {
  const data = state.summary.raw?.companion || state.summary.companion;
  const children = [h('div', { className: 'section-title' }, [h('h2', { text: '考试陪伴' })])];
  if (!data || !data.available) {
    children.push(h('p', { className: 'error-text', text: data?.reason || '计划状态暂不可用，请刷新核对。' }));
  } else {
    children.push(h('p', { text: data.enabled ? '本人私聊计划；回顾需明确同意，无回复不追问。' : data.reason }));
    const labels = { active: '进行中', completed: '已完成', cancelled: '已取消', closed: '已关闭', forgotten: '已遗忘' };
    const consent = { none: '未授权', granted: '已同意一次邀请', revoked: '已撤销' };
    const business = { scheduled: '已安排', blocked: '暂停', expired: '已过期', finished: '步骤已完成', cancelled: '已停止' };
    const transport = { queued: '排队中', sending: '发送中', sent: '已确认发送', unknown: '确认未知',
      rejected_before_send: '发送前拒绝', cancelled: '已停止' };
    const items = data.items.filter(item => {
      const query = state.query.trim().toLowerCase();
      const status = item.status === 'active' ? 'doing' : 'done';
      return (!query || JSON.stringify(item).toLowerCase().includes(query)) &&
        (state.status === 'all' || state.status === status);
    });
    if (!items.length) children.push(h('div', { className: 'empty-state', text: '暂无匹配的本人考试计划。' }));
    items.forEach(item => {
      const body = [h('strong', { text: `${item.plan_id}｜${labels[item.status] || item.status}｜版本 ${item.revision}` }),
        h('p', { text: `本人 ${item.user_id}｜回顾授权：${consent[item.consent] || item.consent}` })];
      if (item.status !== 'forgotten') {
        body.push(h('p', { text: item.title }), h('p', { text: `考试 ${item.exam}；提醒 ${item.reminder_time}（北京时间）` }));
        body.push(h('ul', {}, (item.tasks || []).map(task => h('li', { text: task }))));
        if (item.review_time) body.push(h('p', { text: `回顾邀请 ${item.review_time}（北京时间）` }));
      } else body.push(h('p', { text: '个人正文已清空；历史发送审计仍保留。' }));
      [['提醒', item.reminder], ['回顾邀请', item.invitation]].forEach(([label, step]) => {
        body.push(h('p', { text: `${label}：${business[step.business] || step.business}｜主发送 ${transport[step.transport] || step.transport}｜补记 ${step.effects}${step.reason ? `｜暂停原因 ${step.reason}` : ''}` }));
        if (['sending', 'unknown'].includes(step.transport)) body.push(h('p', { text: '可能已发送，确认未知；自动重发已暂停。' }));
      });
      children.push(h('article', { className: 'work-card companion-card' }, body));
    });
  }
  return h('section', { className: 'panel companion-panel' }, children);
}
