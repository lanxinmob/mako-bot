import { state, navItems, statusOptions } from './state.js';
import { asArray, text, normalizeEvidence, getPercent } from './format.js';

const root = document.getElementById('dashboard-root');

function matchesQuery(item) {
  const query = state.query.trim().toLowerCase();
  if (!query) return true;
  return text(item).toLowerCase().includes(query) || JSON.stringify(item).toLowerCase().includes(query);
}

function matchesStatus(task) {
  return state.status === 'all' || task.status === state.status;
}

function h(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  Object.entries(props || {}).forEach(([key, value]) => {
    if (value === false || value === null || value === undefined) return;
    if (key === 'className') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key === 'html') node.innerHTML = value;
    else if (key.startsWith('on')) node.addEventListener(key.slice(2).toLowerCase(), value);
    else node.setAttribute(key, value === true ? '' : value);
  });
  asArray(children).forEach((child) => node.append(child instanceof Node ? child : document.createTextNode(text(child))));
  return node;
}

function card(title, body, meta = '') {
  return h('article', { className: 'work-card' }, [
    h('div', { className: 'card-head' }, [
      h('strong', { text: title }),
      meta ? h('span', { text: meta }) : ''
    ]),
    body ? h('p', { text: body }) : ''
  ]);
}

function emptyState(message) {
  return h('div', { className: 'empty-state', text: message });
}

function renderDetail(title, summary, bodyNode, meta = '') {
  const details = h('details', { className: 'detail-card' }, [
    h('summary', {}, [
      h('span', { className: 'detail-toggle', 'aria-hidden': 'true' }),
      h('span', { className: 'detail-title' }, [
        h('strong', { text: title }),
        summary ? h('small', { text: summary }) : ''
      ]),
      meta ? h('em', { className: 'detail-meta', text: meta }) : ''
    ]),
    bodyNode
  ]);
  return details;
}

function renderTasks(tasks) {
  const filtered = tasks.filter((task) => matchesQuery(task) && matchesStatus(task));
  if (!filtered.length) return emptyState('没有匹配当前筛选的任务。');
  return h('div', { className: 'task-list' }, filtered.map((task) => {
    const meta = [task.owner, task.due, task.progress !== undefined ? `${task.progress}%` : ''].filter(Boolean).join(' · ');
    const basis = task.completion_basis.length ? task.completion_basis : normalizeEvidence(task.evidence);
    const body = h('div', { className: 'detail-body' }, [
      task.summary ? h('p', { className: 'task-summary', text: task.summary }) : '',
      h('div', { className: 'task-brief-grid' }, [
        task.completion_criteria ? infoBlock('完成标准', task.completion_criteria, 'criteria') : infoBlock('完成标准', '后端暂未提供 completion_criteria。', 'criteria muted'),
        task.why_status ? infoBlock('状态判定', task.why_status, 'status') : infoBlock('状态判定', `当前按 ${task.status_label} 展示。`, 'status muted'),
        basis.length ? infoBlock('依据 / 证据', basis, 'basis') : infoBlock('依据 / 证据', '暂无 completion_basis。', 'basis muted'),
        task.verification ? infoBlock('验证方式', task.verification, 'verify') : infoBlock('验证方式', '等待 verification。', 'verify muted'),
        task.next_step ? infoBlock('下一步', task.next_step, 'next') : infoBlock('下一步', '暂无下一步。', 'next muted')
      ]),
      task.children.length ? renderTasks(task.children) : ''
    ]);
    const node = renderDetail(task.title, task.group || task.summary || task.status_label, body, meta || task.status_label);
    node.classList.add('task-card', `status-${task.status}`);
    return node;
  }));
}

function infoBlock(label, value, tone = '') {
  const values = normalizeEvidence(value);
  return h('section', { className: `info-block ${tone}`.trim() }, [
    h('span', { text: label }),
    values.length > 1
      ? h('ul', {}, values.map((item) => h('li', { text: item })))
      : h('p', { text: values[0] || text(value) || '暂无' })
  ]);
}

function renderOverview(summary) {
  const progress = summary.progress || {};
  const mako = summary.mako_profile || {};
  const recent = summary.recent_progress.filter(matchesQuery).slice(0, 6);
  return [
    h('section', { className: 'hero-panel' }, [
      h('div', {}, [
        h('p', { className: 'eyebrow', text: 'OWNER WORKBENCH' }),
        h('h1', { text: '茉子 Owner 工作台' }),
        h('p', { className: 'hero-copy', text: progress.label || '总览记忆、人物、思考与路线图，把零散线索收成可推进的下一步。' })
      ]),
      h('div', { className: 'hero-stat' }, [
        h('span', { text: `${getPercent(summary)}%` }),
        h('small', { text: progress.streak || '总进度' })
      ])
    ]),
    h('section', { className: 'metric-grid' }, [
      metric('笔记', summary.notes.length),
      metric('人物', summary.people.length),
      metric('思考', summary.thought_traces.length),
      metric('任务', summary.roadmap_tasks.length || summary.roadmap_groups.reduce((sum, group) => sum + group.tasks.length, 0))
    ]),
    h('section', { className: 'content-grid' }, [
      h('div', { className: 'panel span-7' }, [
        h('div', { className: 'section-title' }, [h('h2', { text: '最近进展' })]),
        recent.length ? h('ol', { className: 'timeline' }, recent.map((item) => h('li', {}, [
          h('time', { text: item.time || item.date || item.created_at || '刚刚' }),
          h('span', { text: item.title || item.text || item.content || text(item) })
        ]))) : emptyState('暂无最近进展。')
      ]),
      h('div', { className: 'panel span-5' }, [
        h('div', { className: 'section-title' }, [h('h2', { text: '茉子档案' })]),
        h('dl', { className: 'compact-list' }, [
          row('名字', mako.name || '茉子'),
          row('状态', mako.mood || mako.status || '待命'),
          row('阶段', mako.current_stage || mako.title || '自主意志 v1 修行中'),
          row('价值', asArray(mako.values || mako.traits || mako.tags).join(' / ') || '暂无'),
          row('边界', asArray(mako.boundaries).join(' / ') || '暂无'),
          row('心理画像', asArray(mako.psychological_snapshot).join('；') || mako.summary || '暂无')
        ])
      ])
    ])
  ];
}

function metric(label, value) {
  return h('div', { className: 'metric' }, [h('strong', { text: value }), h('span', { text: label })]);
}

function row(label, value) {
  return h('div', {}, [h('dt', { text: label }), h('dd', { text: value })]);
}

function renderMemory(summary) {
  const notes = summary.notes.filter(matchesQuery);
  const memories = summary.relationship_memories.filter(matchesQuery);
  return h('section', { className: 'content-grid' }, [
    h('div', { className: 'panel span-6' }, [
      h('div', { className: 'section-title' }, [h('h2', { text: '笔记' })]),
      notes.length ? h('div', { className: 'card-stack' }, notes.map((note) => card(
        note.title,
        note.body,
        [note.source, note.date].filter(Boolean).join(' · ')
      ))) : emptyState('没有匹配的笔记。')
    ]),
    h('div', { className: 'panel span-6' }, [
      h('div', { className: 'section-title' }, [h('h2', { text: '关系记忆' })]),
      memories.length ? h('div', { className: 'card-stack' }, memories.map((memory) => card(memory.title, memory.body, memory.date))) : emptyState('没有匹配的关系记忆。')
    ])
  ]);
}

function renderPeople(summary) {
  const people = summary.people.filter(matchesQuery);
  return h('section', { className: 'panel' }, [
    h('div', { className: 'section-title' }, [h('h2', { text: '人物' })]),
    people.length ? h('div', { className: 'people-grid' }, people.map((person) => renderDetail(
      person.name,
      [person.role, person.last_updated ? `更新 ${person.last_updated}` : '', person.memory_count ? `${person.memory_count} 条关系记忆` : ''].filter(Boolean).join(' · ') || '未标注关系',
      h('div', { className: 'detail-body' }, [
        person.summary ? h('p', { className: 'profile-summary', text: person.summary }) : '',
        person.profile_text ? h('div', { className: 'profile-text', text: person.profile_text }) : '',
        person.preferences.length ? h('div', { className: 'tag-row' }, person.preferences.map((tag) => h('span', { text: text(tag) }))) : '',
        person.notes.length ? h('div', { className: 'tag-row' }, person.notes.map((tag) => h('span', { text: text(tag) }))) : '',
        person.relationship_memories.length ? h('div', { className: 'mini-list' }, person.relationship_memories.map((memory) => h('span', {
          text: `${memory.type || '记忆'}：${memory.content || memory.body || text(memory)}`
        }))) : ''
      ])
    ))) : emptyState('没有匹配的人物。')
  ]);
}

function renderThinking(summary) {
  const traces = summary.thought_traces.filter(matchesQuery);
  return h('section', { className: 'panel' }, [
    h('div', { className: 'section-title' }, [h('h2', { text: '思考轨迹' })]),
    traces.length ? h('div', { className: 'card-stack' }, traces.map((trace) => renderDetail(
      trace.title,
      [trace.target_label, trace.date || '思考记录'].filter(Boolean).join(' · '),
      h('div', { className: 'detail-body thought-audit' }, [
        h('div', { className: 'audit-grid' }, [
          infoBlock('触发来源', trace.trigger_source || trace.source, 'trigger'),
          infoBlock('观察到的上下文', trace.context_observed || trace.body, 'context'),
          infoBlock('检索记忆', trace.retrieved_memory.length ? trace.retrieved_memory : '暂无检索记忆', 'memory'),
          infoBlock('决策结果', trace.decision_result || '暂无决策结果', 'decision'),
          infoBlock('最终输出', trace.final_output || trace.body || '暂无最终输出', 'output'),
          infoBlock('安全备注', trace.safety_notes.length ? trace.safety_notes : '暂无安全备注', 'safety'),
          infoBlock('审计备注', trace.audit_note || '暂无审计备注', 'audit')
        ])
      ])
    ))) : emptyState('没有匹配的思考轨迹。')
  ]);
}

function renderRoadmap(summary) {
  const groups = summary.roadmap_groups.length ? summary.roadmap_groups : [{ title: '路线图', tasks: summary.roadmap_tasks }];
  return h('section', { className: 'roadmap-grid' }, groups.map((group) => h('article', { className: 'panel roadmap-panel' }, [
    h('div', { className: 'section-title' }, [
      h('h2', { text: group.title }),
      h('p', { text: `${group.done || 0}/${group.total || (group.tasks || []).length} 完成 · ${group.progress || 0}%` })
    ]),
    h('div', { className: 'group-meter', 'aria-label': `${group.title} ${group.progress || 0}%` }, [
      h('i', { style: `width: ${Math.max(0, Math.min(100, Number(group.progress || 0)))}%` })
    ]),
    group.summary ? h('p', { className: 'group-summary', text: group.summary }) : '',
    renderTasks(group.tasks || [])
  ])));
}

function renderMain() {
  const summary = state.summary;
  if (state.active === 'memory') return renderMemory(summary);
  if (state.active === 'people') return renderPeople(summary);
  if (state.active === 'thinking') return renderThinking(summary);
  if (state.active === 'roadmap') return renderRoadmap(summary);
  return renderOverview(summary);
}

export function createRenderer(events) {
  function render() {
    const percent = getPercent(state.summary);
    root.replaceChildren(
      h('header', { className: 'topbar' }, [
        h('div', { className: 'brand' }, [h('strong', { text: 'Mako' }), h('span', { text: 'Owner 工作台' })]),
        h('nav', { className: 'nav-tabs', 'aria-label': '工作台导航' }, navItems.map(([key, label]) => h('button', {
          type: 'button',
          className: key === state.active ? 'active' : '',
          text: label,
          onClick: () => events.setActive(key)
        }))),
        h('div', { className: 'token-row' }, [
          h('input', {
            value: state.token,
            placeholder: 'Bearer token',
            'aria-label': 'Dashboard token',
            onInput: events.onTokenInput
          }),
          h('button', { type: 'button', text: state.loading ? '读取中' : '刷新', disabled: state.loading, onClick: events.loadSummary })
        ])
      ]),
      h('section', { className: 'toolbar' }, [
        h('label', { className: 'search-box' }, [
          h('span', { text: '搜索' }),
          h('input', {
            value: state.query,
            placeholder: '搜索笔记、人物、任务、思考',
            onInput: events.onQueryInput
          })
        ]),
        h('label', { className: 'status-filter' }, [
          h('span', { text: '任务状态' }),
          h('select', { onChange: events.onStatusChange },
            statusOptions.map(([value, label]) => h('option', { value, text: label, selected: value === state.status }))
          )
        ])
      ]),
      state.error ? h('p', { className: 'error-text', text: state.error }) : '',
      h('div', { className: 'view-stack' }, renderMain()),
      h('footer', { className: 'progress-dock', 'aria-label': `总进度 ${percent}%` }, [
        h('div', {}, [h('strong', { text: '总进度' }), h('span', { text: state.summary.progress.updated_at ? `更新于 ${state.summary.progress.updated_at}` : '等待更新' })]),
        h('div', { className: 'dock-track' }, [h('i', { style: `width: ${percent}%` })]),
        h('b', { text: `${percent}%` })
      ])
    );
  }

  return render;
}
