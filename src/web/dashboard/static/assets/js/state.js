export const TOKEN_KEY = 'mako.dashboard.token';

export const fallbackSummary = {
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

export const navItems = [
  ['overview', '总览'],
  ['memory', '记忆'],
  ['people', '人物'],
  ['thinking', '思考'],
  ['roadmap', '路线图']
];

export const statusOptions = [
  ['all', '全部状态'],
  ['todo', '未开始'],
  ['doing', '进行中'],
  ['done', '已完成'],
  ['blocked', '受阻']
];

export const state = {
  summary: fallbackSummary,
  loading: false,
  error: '',
  token: getInitialToken(),
  active: 'overview',
  query: '',
  status: 'all'
};

function getInitialToken() {
  return localStorage.getItem(TOKEN_KEY) || '';
}
