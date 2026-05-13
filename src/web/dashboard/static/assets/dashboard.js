(function () {
  const API_URL = '/mako/dashboard/api/summary';
  const TOKEN_KEY = 'mako.dashboard.token';

  const fallbackSummary = {
    progress: { percent: 0, label: '等待新的修行卷轴', streak: '未开始', updated_at: '' },
    mako_profile: { name: '茉子', title: '见习忍者手账员', mood: '安静观察中', traits: ['轻步', '认真', '会把碎片整理成地图'] },
    goals: [],
    recent_progress: [],
    notes: [],
    user_profile: { name: '旅人', focus: '还没有写入档案', preferences: [] },
    thinking_summary: ''
  };

  const $ = (id) => document.getElementById(id);

  function asArray(value) {
    if (!value) return [];
    return Array.isArray(value) ? value : [value];
  }

  function text(value) {
    if (value === null || value === undefined) return '';
    return String(value);
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

  function normalizeTask(task, index) {
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
    const source = (data && data.data) || data || {};
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

  function emptyState(title, body) {
    const node = document.createElement('div');
    node.className = 'empty-state';
    node.innerHTML = '<span class="shuriken">✦</span>';
    const strong = document.createElement('strong');
    strong.textContent = title;
    const p = document.createElement('p');
    p.textContent = body;
    node.append(strong, p);
    return node;
  }

  function renderTaskNode(node) {
    const li = document.createElement('li');
    li.className = 'task-node';
    const row = document.createElement('div');
    row.className = 'task-row';

    const mark = document.createElement('b');
    mark.className = node.done ? 'done' : 'todo';
    mark.textContent = node.done ? '✓' : '○';

    const title = document.createElement('span');
    title.textContent = node.title;

    row.append(mark, title);
    if (node.progress !== undefined) {
      const progress = document.createElement('em');
      progress.textContent = `${node.progress}%`;
      row.append(progress);
    }
    li.append(row);

    if (node.children && node.children.length) {
      const ul = document.createElement('ul');
      node.children.forEach((child) => ul.append(renderTaskNode(child)));
      li.append(ul);
    }

    return li;
  }

  function renderSummary(summary) {
    const progress = summary.progress || {};
    const percent = Math.max(0, Math.min(100, Number(progress.percent ?? progress.value ?? progress.total) || 0));
    const mako = summary.mako_profile || {};
    const user = summary.user_profile || {};

    $('progress-label').textContent = progress.label || '把目标、笔记和思考线索收进同一本卷轴。';
    $('progress-value').textContent = percent;
    $('progress-ring').style.setProperty('--progress', `${percent * 3.6}deg`);
    $('progress-ring').setAttribute('aria-label', `总进度 ${percent}%`);
    $('progress-streak').textContent = progress.streak || '今日静候任务';
    $('progress-updated').textContent = progress.updated_at ? `更新于 ${progress.updated_at}` : '卷轴边缘还留着空白';

    $('mako-name').textContent = mako.name || '茉子';
    $('mako-title').textContent = mako.title || mako.role || '见习忍者手账员';
    $('mako-mood').textContent = mako.mood || mako.status || '安静观察中';
    $('mako-traits').textContent = asArray(mako.traits || mako.tags).join(' / ') || '暂无';

    const taskTree = $('task-tree');
    taskTree.replaceChildren();
    if (summary.goals && summary.goals.length) {
      const ul = document.createElement('ul');
      ul.className = 'task-tree';
      summary.goals.forEach((goal) => ul.append(renderTaskNode(goal)));
      taskTree.append(ul);
    } else {
      taskTree.append(emptyState('任务卷轴未展开', '茉子已经磨好墨，等第一枚目标落在纸上。'));
    }

    const recent = $('recent-progress');
    recent.replaceChildren();
    if (summary.recent_progress && summary.recent_progress.length) {
      const ol = document.createElement('ol');
      ol.className = 'timeline';
      summary.recent_progress.forEach((item) => {
        const li = document.createElement('li');
        const time = document.createElement('time');
        time.textContent = item.time || item.date || item.created_at || '刚刚';
        const span = document.createElement('span');
        span.textContent = item.title || item.text || item.content || text(item);
        li.append(time, span);
        ol.append(li);
      });
      recent.append(ol);
    } else {
      recent.append(emptyState('脚印还很浅', '完成一点点也算数，茉子会帮你记住。'));
    }

    const notes = $('notes');
    notes.replaceChildren();
    if (summary.notes && summary.notes.length) {
      const stack = document.createElement('div');
      stack.className = 'note-stack';
      summary.notes.forEach((note, index) => {
        const article = document.createElement('article');
        article.className = 'note';
        const title = document.createElement('strong');
        title.textContent = note.title || note.topic || `手账 ${index + 1}`;
        const body = document.createElement('p');
        body.textContent = note.body || note.text || note.content || text(note);
        article.append(title, body);
        stack.append(article);
      });
      notes.append(stack);
    } else {
      notes.append(emptyState('纸页暂时清亮', '没有笔记时，茉子会把空白也收拾得很整齐。'));
    }

    $('user-name').textContent = user.name || user.nickname || '旅人';
    $('user-focus').textContent = user.focus || user.current_focus || '还没有写入档案';
    $('user-preferences').textContent = asArray(user.preferences || user.tags).join(' / ') || '暂无';

    const thinking = $('thinking-summary');
    thinking.replaceChildren();
    if (summary.thinking_summary) {
      const p = document.createElement('p');
      p.className = 'thinking-copy';
      p.textContent = summary.thinking_summary;
      thinking.append(p);
    } else {
      thinking.append(emptyState('思路正在潜行', '等摘要抵达，茉子会把它折成一张清楚的忍者便签。'));
    }
  }

  function setError(message) {
    const error = $('error-text');
    if (!message) {
      error.hidden = true;
      error.textContent = '';
      return;
    }
    error.hidden = false;
    error.textContent = message;
  }

  async function loadSummary() {
    const token = $('token-input').value.trim();
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);

    if (!token) {
      setError('把 token 放进 URL query，或在本机 localStorage 写入 mako.dashboard.token。');
      renderSummary(fallbackSummary);
      return;
    }

    $('reload-button').disabled = true;
    $('reload-button').querySelector('span').textContent = '读取中';
    setError('');

    try {
      const response = await fetch(API_URL, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (!response.ok) throw new Error(`卷轴读取失败：HTTP ${response.status}`);
      const payload = await response.json();
      renderSummary(normalizeSummary(payload));
    } catch (error) {
      renderSummary(fallbackSummary);
      setError(error.message || '卷轴读取失败');
    } finally {
      $('reload-button').disabled = false;
      $('reload-button').querySelector('span').textContent = '刷新';
    }
  }

  $('token-input').value = getInitialToken();
  $('reload-button').addEventListener('click', loadSummary);
  renderSummary(fallbackSummary);
  loadSummary();
})();
