import React from 'react';
import { createRoot } from 'react-dom/client';
import { Activity, BookOpen, Brain, CheckCircle2, Circle, ClipboardList, FileText, Leaf, RefreshCw, ScrollText, Sparkles, Target, UserRound } from 'lucide-react';
import './styles.css';

const API_URL = '/mako/dashboard/api/summary';
const TOKEN_KEY = 'mako.dashboard.token';

const fallbackSummary = {
  progress: {
    percent: 0,
    label: '等待新的修行卷轴',
    streak: '未开始',
    updated_at: ''
  },
  mako_profile: {
    name: '茉子',
    title: '见习忍者手账员',
    mood: '安静观察中',
    traits: ['轻步', '认真', '会把碎片整理成地图']
  },
  goals: [],
  recent_progress: [],
  notes: [],
  user_profile: {
    name: '旅人',
    focus: '还没有写入档案',
    preferences: []
  },
  thinking_summary: ''
};

function getInitialToken() {
  const params = new URLSearchParams(window.location.search);
  const queryToken = params.get('token') || params.get('auth_token');
  if (queryToken) {
    localStorage.setItem(TOKEN_KEY, queryToken);
    return queryToken;
  }
  return localStorage.getItem(TOKEN_KEY) || '';
}

function asArray(value) {
  if (!value) return [];
  return Array.isArray(value) ? value : [value];
}

function normalizeTask(task, index = 0) {
  if (typeof task === 'string') {
    return { id: `task-${index}`, title: task, done: false, children: [] };
  }
  return {
    id: task.id || task.key || `task-${index}`,
    title: task.title || task.name || task.label || '未命名任务',
    done: Boolean(task.done || task.completed || task.status === 'done'),
    progress: task.progress,
    children: asArray(task.children || task.tasks || task.items).map(normalizeTask)
  };
}

function normalizeSummary(data) {
  const source = data?.data || data || {};
  return {
    ...fallbackSummary,
    ...source,
    progress: { ...fallbackSummary.progress, ...(source.progress || source.total_progress || {}) },
    mako_profile: { ...fallbackSummary.mako_profile, ...(source.mako_profile || source.mako || {}) },
    goals: asArray(source.goals || source.tasks || source.task_tree).map(normalizeTask),
    recent_progress: asArray(source.recent_progress || source.recent || source.timeline),
    notes: asArray(source.notes),
    user_profile: { ...fallbackSummary.user_profile, ...(source.user_profile || source.user || {}) },
    thinking_summary: source.thinking_summary || source.thoughts || source.summary || ''
  };
}

function useSummary() {
  const [token, setToken] = React.useState(getInitialToken);
  const [summary, setSummary] = React.useState(fallbackSummary);
  const [state, setState] = React.useState({ loading: true, error: '' });

  const load = React.useCallback(async () => {
    if (!token) {
      setState({ loading: false, error: '把 token 放进 URL query，或在本机 localStorage 写入 mako.dashboard.token。' });
      setSummary(fallbackSummary);
      return;
    }

    setState({ loading: true, error: '' });
    try {
      const response = await fetch(API_URL, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (!response.ok) throw new Error(`卷轴读取失败：HTTP ${response.status}`);
      const payload = await response.json();
      setSummary(normalizeSummary(payload));
      setState({ loading: false, error: '' });
    } catch (error) {
      setSummary(fallbackSummary);
      setState({ loading: false, error: error.message || '卷轴读取失败' });
    }
  }, [token]);

  React.useEffect(() => {
    load();
  }, [load]);

  const rememberToken = (nextToken) => {
    setToken(nextToken);
    if (nextToken) localStorage.setItem(TOKEN_KEY, nextToken);
    else localStorage.removeItem(TOKEN_KEY);
  };

  return { summary, token, setToken: rememberToken, reload: load, ...state };
}

function ProgressRing({ value }) {
  const percent = Math.max(0, Math.min(100, Number(value) || 0));
  return (
    <div className="progress-ring" style={{ '--progress': `${percent * 3.6}deg` }} aria-label={`总进度 ${percent}%`}>
      <span>{percent}</span>
      <small>%</small>
    </div>
  );
}

function EmptyState({ title, text }) {
  return (
    <div className="empty-state">
      <span className="shuriken">✦</span>
      <strong>{title}</strong>
      <p>{text}</p>
    </div>
  );
}

function Section({ icon: Icon, title, children, className = '' }) {
  return (
    <section className={`panel ${className}`}>
      <div className="section-title">
        <Icon size={18} aria-hidden="true" />
        <h2>{title}</h2>
      </div>
      {children}
    </section>
  );
}

function TaskNode({ node, depth = 0 }) {
  return (
    <li className="task-node" style={{ '--depth': depth }}>
      <div className="task-row">
        {node.done ? <CheckCircle2 size={17} className="done" /> : <Circle size={17} className="todo" />}
        <span>{node.title}</span>
        {node.progress !== undefined && <em>{node.progress}%</em>}
      </div>
      {node.children?.length > 0 && (
        <ul>
          {node.children.map((child, index) => (
            <TaskNode key={child.id || `${node.id}-${index}`} node={child} depth={depth + 1} />
          ))}
        </ul>
      )}
    </li>
  );
}

function App() {
  const { summary, token, setToken, loading, error, reload } = useSummary();
  const progress = summary.progress || {};
  const mako = summary.mako_profile || {};
  const user = summary.user_profile || {};

  return (
    <main className="app-shell">
      <header className="hero">
        <div className="hero-copy">
          <div className="eyebrow"><Leaf size={16} /> 忍者手账</div>
          <h1>茉子的修行看板</h1>
          <p>{progress.label || '把目标、笔记和思考线索收进同一本卷轴。'}</p>
          <div className="token-row">
            <input
              value={token}
              onChange={(event) => setToken(event.target.value.trim())}
              placeholder="Bearer token"
              aria-label="Dashboard token"
            />
            <button type="button" onClick={reload} disabled={loading}>
              <RefreshCw size={16} />
              <span>{loading ? '读取中' : '刷新'}</span>
            </button>
          </div>
          {error && <p className="error-text">{error}</p>}
        </div>
        <div className="hero-progress">
          <ProgressRing value={progress.percent ?? progress.value ?? progress.total} />
          <div>
            <strong>{progress.streak || '今日静候任务'}</strong>
            <span>{progress.updated_at ? `更新于 ${progress.updated_at}` : '卷轴边缘还留着空白'}</span>
          </div>
        </div>
      </header>

      <div className="dashboard-grid">
        <Section icon={UserRound} title="茉子档案" className="profile-panel">
          <div className="profile-card">
            <div className="avatar">茉</div>
            <div>
              <h3>{mako.name || '茉子'}</h3>
              <p>{mako.title || mako.role || '见习忍者手账员'}</p>
            </div>
          </div>
          <dl className="compact-list">
            <div><dt>状态</dt><dd>{mako.mood || mako.status || '安静观察中'}</dd></div>
            <div><dt>标记</dt><dd>{asArray(mako.traits || mako.tags).join(' / ') || '暂无'}</dd></div>
          </dl>
        </Section>

        <Section icon={Target} title="目标 / 任务树" className="tasks-panel">
          {summary.goals?.length ? (
            <ul className="task-tree">
              {summary.goals.map((goal, index) => <TaskNode key={goal.id || index} node={goal} />)}
            </ul>
          ) : (
            <EmptyState title="任务卷轴未展开" text="茉子已经磨好墨，等第一枚目标落在纸上。" />
          )}
        </Section>

        <Section icon={Activity} title="最近进展">
          {summary.recent_progress?.length ? (
            <ol className="timeline">
              {summary.recent_progress.map((item, index) => (
                <li key={item.id || index}>
                  <time>{item.time || item.date || item.created_at || '刚刚'}</time>
                  <span>{item.title || item.text || item.content || item}</span>
                </li>
              ))}
            </ol>
          ) : (
            <EmptyState title="脚印还很浅" text="完成一点点也算数，茉子会帮你记住。" />
          )}
        </Section>

        <Section icon={BookOpen} title="笔记">
          {summary.notes?.length ? (
            <div className="note-stack">
              {summary.notes.map((note, index) => (
                <article className="note" key={note.id || index}>
                  <strong>{note.title || note.topic || `手账 ${index + 1}`}</strong>
                  <p>{note.body || note.text || note.content || note}</p>
                </article>
              ))}
            </div>
          ) : (
            <EmptyState title="纸页暂时清亮" text="没有笔记时，茉子会把空白也收拾得很整齐。" />
          )}
        </Section>

        <Section icon={ClipboardList} title="用户档案">
          <dl className="compact-list">
            <div><dt>名字</dt><dd>{user.name || user.nickname || '旅人'}</dd></div>
            <div><dt>关注</dt><dd>{user.focus || user.current_focus || '还没有写入档案'}</dd></div>
            <div><dt>偏好</dt><dd>{asArray(user.preferences || user.tags).join(' / ') || '暂无'}</dd></div>
          </dl>
        </Section>

        <Section icon={Brain} title="思考摘要" className="thinking-panel">
          {summary.thinking_summary ? (
            <p className="thinking-copy">{summary.thinking_summary}</p>
          ) : (
            <EmptyState title="思路正在潜行" text="等摘要抵达，茉子会把它折成一张清楚的忍者便签。" />
          )}
        </Section>
      </div>

      <footer>
        <ScrollText size={16} />
        <span>API: GET {API_URL}</span>
        <Sparkles size={16} />
      </footer>
    </main>
  );
}

createRoot(document.getElementById('root')).render(<App />);
