import { state } from './state.js';

const actions = { ignore: '沉默', wait: '等待', reply: '准备回应' };
const stages = { observed: '仅观察，未进入普通聊天', waiting: '等待合并消息',
  candidate: '候选回复', generating: '生成中', canceled: '候选已取消', finished: '本次处理结束' };
const sends = { not_started: '尚未发送', in_flight: '已开始发送', confirmed: '适配器已确认',
  unknown: '发送确认未知', failed: '发送明确失败' };

export function renderRhythm(h) {
  const items = state.rhythm?.items || [];
  return h('section', { className: 'panel', 'aria-label': '群聊节奏' }, [
    h('h2', { text: '最近群聊节奏' }),
    h('p', { text: '仅当前进程最近30分钟，最多200条；重启后清空。工具和提醒由独立流程处理。' }),
    h('p', { text: '这里的发送确认来自适配器，不表示对方已读。候选取消后，已开始的发送仍可能送达。' }),
    state.rhythmError ? h('p', { className: 'error-text', text: state.rhythmError }) :
      !state.rhythm ? h('p', { text: '请使用已配置的 token 刷新以读取状态。' }) :
      !items.length ? h('p', { className: 'empty-state', text: '暂无记录' }) :
      h('div', { className: 'card-stack' }, items.map(item => h('article', { className: 'work-card' }, [
        h('strong', { text: actions[item.action] || '仅观察' }),
        h('p', { text: item.reason_label || '未产生普通聊天参与判断' }),
        h('p', { text: `${stages[item.stage] || '未知阶段'} · ${sends[item.send_state] || '未知发送状态'}` }),
        item.action === 'wait' && Number.isFinite(item.wait_ms) ? h('p', { text: `本次合并等待 ${(item.wait_ms / 1000).toFixed(1)} 秒` }) : '',
        item.outcome_reason_label ? h('p', { text: item.outcome_reason_label }) : '',
        item.late_cancel ? h('p', { text: '撤回或上下文变化发生在发送开始后，请核对实际送达。' }) : '',
        h('small', { text: `${item.group_alias} · ${item.target_alias} · ${item.updated_at}` })
      ])))
  ]);
}
