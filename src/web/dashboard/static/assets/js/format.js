import { fallbackSummary } from './state.js';

export function asArray(value) {
  if (!value) return [];
  return Array.isArray(value) ? value : [value];
}

export function text(value) {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return value.title || value.name || value.label || value.summary || value.content || JSON.stringify(value);
}

export function cleanProfileText(value) {
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

export function firstUsefulLine(value) {
  const cleaned = cleanProfileText(value);
  return cleaned.split('\n').map((line) => line.trim()).find(Boolean) || '';
}

export function normalizeStatus(value, done) {
  const raw = String(value || '').toLowerCase();
  if (done || ['done', 'complete', 'completed', 'finished'].includes(raw)) return 'done';
  if (['doing', 'in_progress', 'active', 'working', 'running'].includes(raw)) return 'doing';
  if (['blocked', 'stuck', 'paused', 'waiting'].includes(raw)) return 'blocked';
  return 'todo';
}

export function firstValue(...values) {
  return values.find((value) => text(value).trim()) || '';
}

export function normalizeEvidence(value) {
  if (!value) return [];
  return asArray(value).flatMap((item) => {
    if (!item) return [];
    if (Array.isArray(item)) return normalizeEvidence(item);
    return [text(item)];
  }).filter(Boolean);
}

export function normalizeTask(task, index = 0, group = '') {
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

export function normalizePerson(person, index) {
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

export function normalizeNote(note, index, type = 'note') {
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

export function normalizeRoadmapGroups(source) {
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

export function normalizeSummary(data) {
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

export function getPercent(summary) {
  const progress = summary.progress || {};
  return Math.max(0, Math.min(100, Number(progress.percent ?? progress.value ?? progress.total) || 0));
}

export function statusLabel(status) {
  return ({ todo: '未开始', doing: '进行中', done: '已完成', blocked: '受阻' })[status] || '未开始';
}
