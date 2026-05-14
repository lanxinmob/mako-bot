(function () {
  const API_URL = '/mako/dashboard/api/summary';
  const TOKEN_KEY = 'mako.dashboard.token';

  const fallbackSummary = {
    progress: { percent: 0, label: '等待工作台数据', streak: '未开始', updated_at: '' },
    recent_progress: [],
    notes: [],
    people: [],
    relationship_memories: [],
    mako_profile: { name: '茉子', title: 'Owner 工作台助手', mood: '待命', traits: ['整理线索', '跟进路线图'] },
    thought_traces: [],
    roadmap_tasks: [],
    roadmap_groups: [],
    user_profile: { name: 'Owner', focus: '还没有写入档案', preferences: [] },
    goals: [],
    tasks: [],
    raw: null
  };

  const navItems = [
    ['overview', '总览'],
    ['memory', '记忆'],
    ['people', '人物'],
    ['thinking', '思考'],
    ['roadmap', '路线图']
  ];

  const statusOptions = [
    ['all', '全部状态'],
    ['todo', '未开始'],
    ['doing', '进行中'],
    ['done', '已完成'],
    ['blocked', '受阻']
  ];

  const root = document.getElementById('dashboard-root');
  let state = {
    summary: fallbackSummary,
    loading: false,
    error: '',
    token: getInitialToken(),
    active: 'overview',
    query: '',
    status: 'all'
  };

  function asArray(value) {
    if (!value) return [];
    return Array.isArray(value) ? value : [value];
  }

  function text(value) {
    if (value === null || value === undefined) return '';
    if (typeof value === 'string') return value;
    if (typeof value === 'number' || typeof value === 'boolean') return String(value);
    return value.title || value.name || value.label || value.summary || value.content || JSON.stringify(value);
  }

  function cleanProfileText(value) {
    let raw = text(value).trim();
    raw = raw.replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/i, '').trim();
    try {
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === 'object') {
        return cleanProfileText(parsed.profile_text || parsed.summary || parsed.content || '');
      }
    } catch (_error) {
      // Plain profile text is expected for most records.
    }
    return raw.replace(/\\n/g, '\n').trim();
  }

  function firstUsefulLine(value) {
    const cleaned = cleanProfileText(value);
    return cleaned.split('\n').map((line) => line.trim()).find(Boolean) || '';
  }

  function getInitialToken() {
    const params = new URLSearchParams(window.location.search);
    const queryToken = params.get('token') || params.get('auth_token');
    if (queryToken) {
      localStorage.setItem(TOKEN_KEY, queryToken);
      return queryToken;
    }
    return localStorage.getItem(TOKEN_KEY) || '';
  }

  function normalizeStatus(value, done) {
    const raw = String(value || '').toLowerCase();
    if (done || ['done', 'complete', 'completed', 'finished'].includes(raw)) return 'done';
    if (['doing', 'in_progress', 'active', 'working', 'running'].includes(raw)) return 'doing';
    if (['blocked', 'stuck', 'paused', 'waiting'].includes(raw)) return 'blocked';
    return 'todo';
  }

  function firstValue(...values) {
    return values.find((value) => text(value).trim()) || '';
  }

  function normalizeEvidence(value) {
    if (!value) return [];
    return asArray(value).flatMap((item) => {
      if (!item) return [];
      if (Array.isArray(item)) return normalizeEvidence(item);
      return [text(item)];
    }).filter(Boolean);
  }

  function normalizeTask(task, index = 0, group = '') {
    if (typeof task === 'string') {
      return {
        id: `task-${index}`,
        title: task,
        status: 'todo',
        status_label: statusLabel('todo'),
        done: false,
        completion_criteria: '',
        completion_basis: [],
        verification: '',
        why_status: '',
        next_step: '',
        children: [],
        group
      };
    }
    const done = Boolean(task.done || task.completed || task.status === 'done');
    const status = normalizeStatus(task.status || task.state, done);
    return {
      id: task.id || task.key || `${group || 'task'}-${index}`,
      title: task.title || task.name || task.label || '未命名任务',
      summary: task.summary || task.description || task.detail || task.body || '',
      status,
      done: status === 'done',
      progress: task.progress ?? task.percent,
      owner: task.owner || task.assignee || '',
      due: task.due || task.due_at || task.date || '',
      status_label: task.status_label || statusLabel(status),
      completion_criteria: firstValue(task.completion_criteria, task.acceptance_criteria, task.done_when),
      completion_basis: normalizeEvidence(task.completion_basis || task.basis || task.evidence),
      verification: firstValue(task.verification, task.verify, task.test_plan),
      why_status: firstValue(task.why_status, task.status_reason, task.reason),
      next_step: firstValue(task.next_step, task.next, task.action, task.todo_next),
      group,
      children: asArray(task.children || task.tasks || task.items).map((child, childIndex) => normalizeTask(child, childIndex, group))
    };
  }

  function normalizePerson(person, index) {
    if (typeof person === 'string') return { id: `person-${index}`, name: person, role: '', notes: [] };
    const profileText = cleanProfileText(person.profile_text || person.profile || person.body || '');
    return {
      id: person.id || person.key || `person-${index}`,
      name: person.name || person.nickname || person.title || `人物 ${index + 1}`,
      role: person.role || person.relationship || person.label || `QQ ${person.user_id || ''}`.trim(),
      summary: person.summary || person.description || person.focus || firstUsefulLine(profileText),
      profile_text: profileText,
      preferences: asArray(person.preferences),
      notes: asArray(person.notes || person.memories || person.tags),
      relationship_memories: asArray(person.relationship_memories || person.relationships),
      memory_count: Number(person.memory_count || 0),
      last_updated: person.last_updated || person.updated_at || ''
    };
  }

  function normalizeNote(note, index, type = 'note') {
    if (typeof note === 'string') {
      return {
        id: `${type}-${index}`,
        title: `${type === 'memory' ? '记忆' : '笔记'} ${index + 1}`,
        body: note,
        tags: [],
        trigger_source: '',
        context_observed: '',
        retrieved_memory: [],
        decision_result: '',
        final_output: '',
        safety_notes: [],
        audit_note: '',
        target_label: ''
      };
    }
    return {
      id: note.id || note.key || `${type}-${index}`,
      title: note.title || note.topic || note.name || note.target_label || note.type || note.trace_type || `${type === 'memory' ? '记忆' : '笔记'} ${index + 1}`,
      body: note.body || note.text || note.content || note.summary || note.final_output || '',
      date: note.date || note.created_at || note.updated_at || note.time || '',
      tags: asArray(note.tags || note.keywords || note.people || note.category),
      source: note.source || type,
      trigger_source: note.trigger_source || note.source_event || '',
      context_observed: note.context_observed || note.context || '',
      retrieved_memory: normalizeEvidence(note.retrieved_memory || note.memory_used || note.memories_used),
      decision_result: note.decision_result || note.decision || '',
      final_output: note.final_output || note.output || '',
      safety_notes: normalizeEvidence(note.safety_notes || note.safety || note.guardrails),
      audit_note: note.audit_note || note.audit || '',
      target_label: note.target_label || note.target || note.subject || ''
    };
  }

  function normalizeRoadmapGroups(source) {
    const groups = asArray(source.roadmap_groups || source.groups);
    if (groups.length) {
      return groups.map((group, index) => {
        if (typeof group === 'string') return { id: `group-${index}`, title: group, tasks: [] };
        return {
          id: group.id || group.key || `group-${index}`,
          title: group.title || group.name || group.label || `阶段 ${index + 1}`,
          summary: group.summary || group.description || '',
          tasks: asArray(group.tasks || group.items).map((task, taskIndex) => normalizeTask(task, taskIndex, group.title || group.name || ''))
        };
      });
    }
    const oldGoals = asArray(source.goals || source.tasks || source.task_tree).map((task, index) => normalizeTask(task, index, '旧任务'));
    return oldGoals.length ? [{ id: 'legacy', title: '旧任务', tasks: oldGoals }] : [];
  }

  function normalizeSummary(data) {
    const source = (data && data.data) || data || {};
    const roadmapGroups = normalizeRoadmapGroups(source);
    const roadmapTasks = asArray(source.roadmap_tasks || source.tasks || source.goals || source.task_tree).map((task, index) => normalizeTask(task, index));
    return {
      ...fallbackSummary,
      ...source,
      progress: { ...fallbackSummary.progress, ...(source.progress || source.total_progress || {}) },
      mako_profile: { ...fallbackSummary.mako_profile, ...(source.mako_profile || source.mako || {}) },
      user_profile: { ...fallbackSummary.user_profile, ...(source.user_profile || source.user || {}) },
      notes: asArray(source.memory_notes || source.notes).map((note, index) => normalizeNote(note, index)),
      people: asArray(source.people).map(normalizePerson),
      relationship_memories: asArray(source.relationship_memories || source.memories).map((note, index) => normalizeNote(note, index, 'memory')),
      thought_traces: asArray(source.thought_traces || source.thinking_summary || source.thoughts || source.summary).map((note, index) => normalizeNote(note, index, 'thought')),
      roadmap_tasks: roadmapTasks,
      roadmap_groups: roadmapGroups,
      goals: roadmapTasks,
      raw: source.raw || source
    };
  }

  function getPercent(summary) {
    const progress = summary.progress || {};
    return Math.max(0, Math.min(100, Number(progress.percent ?? progress.value ?? progress.total) || 0));
  }

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

  function statusLabel(status) {
    return ({ todo: '未开始', doing: '进行中', done: '已完成', blocked: '受阻' })[status] || '未开始';
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

  function render() {
    const percent = getPercent(state.summary);
    root.replaceChildren(
      h('header', { className: 'topbar' }, [
        h('div', { className: 'brand' }, [h('strong', { text: 'Mako' }), h('span', { text: 'Owner 工作台' })]),
        h('nav', { className: 'nav-tabs', 'aria-label': '工作台导航' }, navItems.map(([key, label]) => h('button', {
          type: 'button',
          className: key === state.active ? 'active' : '',
          text: label,
          onClick: () => { state.active = key; render(); }
        }))),
        h('div', { className: 'token-row' }, [
          h('input', {
            value: state.token,
            placeholder: 'Bearer token',
            'aria-label': 'Dashboard token',
            onInput: (event) => {
              state.token = event.target.value.trim();
              if (state.token) localStorage.setItem(TOKEN_KEY, state.token);
              else localStorage.removeItem(TOKEN_KEY);
            }
          }),
          h('button', { type: 'button', text: state.loading ? '读取中' : '刷新', disabled: state.loading, onClick: loadSummary })
        ])
      ]),
      h('section', { className: 'toolbar' }, [
        h('label', { className: 'search-box' }, [
          h('span', { text: '搜索' }),
          h('input', {
            value: state.query,
            placeholder: '搜索笔记、人物、任务、思考',
            onInput: (event) => { state.query = event.target.value; render(); }
          })
        ]),
        h('label', { className: 'status-filter' }, [
          h('span', { text: '任务状态' }),
          h('select', { onChange: (event) => { state.status = event.target.value; render(); } },
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

  async function loadSummary() {
    if (!state.token) {
      state.error = '把 token 放进 URL query，或在本机 localStorage 写入 mako.dashboard.token。';
      state.summary = fallbackSummary;
      render();
      return;
    }
    state.loading = true;
    state.error = '';
    render();
    try {
      const response = await fetch(API_URL, { headers: { Authorization: `Bearer ${state.token}` } });
      if (!response.ok) throw new Error(`工作台读取失败：HTTP ${response.status}`);
      const payload = await response.json();
      state.summary = normalizeSummary(payload);
    } catch (error) {
      state.summary = fallbackSummary;
      state.error = error.message || '工作台读取失败';
    } finally {
      state.loading = false;
      render();
    }
  }

  render();
  loadSummary();
})();
