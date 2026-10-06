/* Run with the bundled Playwright through NODE_PATH; all HTTP is intercepted. */
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const { createHash } = require('node:crypto');

const root = process.cwd();
assert.ok(fs.existsSync(path.join(root, 'pyproject.toml')), 'Run from the project root');
const assets = path.join(root, 'src/web/dashboard/static');
const phase = process.argv[2] || 'R12';
assert.ok(['R12', 'R13'].includes(phase));
const output = path.join(root, 'docs/refactor/records/dashboard/artifacts', phase);
const old = new Map(['index.html', 'assets/dashboard.js', 'assets/dashboard.css'].map(file => [
  file, execFileSync('git', ['show', `8fdb8e542836bb616bfa5c426ca5ac9cf6dde7e9:src/web/dashboard/static/${file}`], { encoding: 'utf8' })
]));
const headers = {
  'Content-Security-Policy': "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'",
  'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer', 'X-Content-Type-Options': 'nosniff'
};
const dangerous = '<img src="https://external.invalid/never" onerror="window.injected=true">';
const task = (status, index) => ({
  id: `t-${index}`, title: `任务 ${index}`, summary: '固定样例', status,
  completion_criteria: ['检查输入', '保留输出'], completion_basis: ['本地依据'],
  why_status: '固定状态', verification: '受控检查', next_step: '下一步', children: []
});
const tasks = ['done', 'doing', 'blocked', 'todo'].map(task);
const fixture = { ok: true, data: {
  progress: { percent: 25, updated_at: '2026-01-02 03:04', streak: '固定进度' },
  recent_progress: [{ time: '03:04', title: '固定进展' }],
  mako_profile: { name: '茉子', summary: '固定画像', values: ['边界'], psychological_snapshot: ['可核查'] },
  notes: Array.from({ length: 24 }, (_, i) => ({ id: `n-${i}`, title: `笔记 ${i}`, content: `${dangerous} 中文长内容 `.repeat(4) })),
  people: [{ id: 'p-1', name: '测试人物', profile_text: '【偏好】\n- 测试', relationship_memories: [] }],
  relationship_memories: [{ id: 'm-1', content: '固定记忆' }],
  thought_traces: [{ id: 'trace', title: '旧轨迹', summary: '固定轨迹', payload: { action: 'silent' } }],
  roadmap_tasks: tasks, roadmap_groups: [{ id: 'g', title: '固定路线', tasks }]
} };
const digest = data => createHash('sha256').update(JSON.stringify(data)).digest('hex');

async function snapshot(page, label) {
  const data = await page.evaluate(() => {
    const el = document.getElementById('dashboard-root');
    return {
      dom: el.innerHTML,
      size: [document.documentElement.scrollWidth, innerWidth],
      layout: [...el.querySelectorAll('*')].map(node => {
        const r = node.getBoundingClientRect();
        const s = getComputedStyle(node);
        return [node.tagName, r.x, r.y, r.width, r.height, s.display, s.color, s.backgroundColor,
          s.fontSize, s.gridTemplateColumns, s.position, s.outlineStyle, s.outlineWidth];
      })
    };
  });
  return { label, ...data };
}

async function exercise(browser, baseline, width) {
  const context = await browser.newContext({ viewport: { width, height: 900 } });
  const page = await context.newPage();
  const errors = [];
  const forbidden = [];
  const requests = [];
  const snapshots = [];
  let replyMode = 'fixture';
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(() => {
    window.cspViolations = [];
    document.addEventListener('securitypolicyviolation', event => window.cspViolations.push(event.violatedDirective));
  });
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== 'http://dashboard.test') {
      forbidden.push(url.href);
      return route.abort();
    }
    if (url.pathname === '/mako/dashboard/api/summary') {
      const authorization = route.request().headers().authorization;
      requests.push(authorization);
      if (authorization !== 'Bearer synthetic-good') {
        return route.fulfill({ status: 401, contentType: 'application/json', body: '{}' });
      }
      if (replyMode === 'failure') return route.abort('failed');
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(replyMode === 'empty' ? {} : fixture) });
    }
    const rel = url.pathname === '/mako/dashboard' ? 'index.html' : url.pathname.replace('/mako/dashboard/', '');
    const target = path.resolve(assets, rel);
    if (!target.startsWith(assets + path.sep) || !fs.existsSync(target)) {
      forbidden.push(url.href);
      return route.abort();
    }
    const useOld = baseline && (phase === 'R12' || rel === 'assets/dashboard.css');
    const body = useOld && old.has(rel) ? old.get(rel) : fs.readFileSync(target, 'utf8');
    const contentType = rel.endsWith('.js') ? 'text/javascript' : rel.endsWith('.css') ? 'text/css' : 'text/html';
    return route.fulfill({ status: 200, headers, contentType, body });
  });
  await page.goto('http://dashboard.test/mako/dashboard?token=ignored');
  await page.getByText('请输入 Dashboard token；', { exact: false }).waitFor();
  assert.equal(requests.length, 0);
  snapshots.push(await snapshot(page, 'no-token'));
  await page.getByLabel('Dashboard token').fill(' synthetic-wrong ');
  await page.getByRole('button', { name: '刷新', exact: true }).click();
  await page.getByText('工作台读取失败：HTTP 401', { exact: true }).waitFor();
  snapshots.push(await snapshot(page, '401'));
  await page.getByLabel('Dashboard token').fill(' synthetic-good ');
  await page.getByRole('button', { name: '刷新', exact: true }).click();
  await page.getByText('固定进展', { exact: true }).waitFor();
  assert.equal(await page.evaluate(() => localStorage.getItem('mako.dashboard.token')), 'synthetic-good');
  await page.locator('body').click({ position: { x: 1, y: 1 } });
  snapshots.push(await snapshot(page, 'overview'));
  await page.screenshot({ path: path.join(output, `${phase}-${baseline ? 'before' : 'after'}-${width}-overview.png`) });
  for (const tab of ['记忆', '人物', '思考', '路线图']) {
    await page.getByRole('button', { name: tab, exact: true }).click();
    snapshots.push(await snapshot(page, tab));
    if (tab === '记忆') {
      assert.equal(await page.locator('.view-stack img').count(), 0);
      await page.screenshot({ path: path.join(output, `${phase}-${baseline ? 'before' : 'after'}-${width}-memory.png`) });
    }
    if (tab === '人物' || tab === '思考') {
      await page.locator('details summary').first().click();
      snapshots.push(await snapshot(page, `${tab}-expanded`));
    }
  }
  await page.getByRole('combobox').selectOption('done');
  assert.equal(await page.locator('.task-card').count(), 1);
  snapshots.push(await snapshot(page, 'done-filter'));
  await page.locator('.task-card summary').click();
  snapshots.push(await snapshot(page, 'task-expanded'));
  await page.getByPlaceholder('搜索笔记、人物、任务、思考').fill('no-such-fixture');
  await page.getByText('没有匹配当前筛选的任务。', { exact: true }).waitFor();
  snapshots.push(await snapshot(page, 'search-empty'));
  await page.getByPlaceholder('搜索笔记、人物、任务、思考').fill('');
  await page.getByRole('combobox').selectOption('all');
  await page.getByRole('button', { name: '总览', exact: true }).click();
  await page.getByLabel('Dashboard token').focus();
  snapshots.push(await snapshot(page, 'token-focus'));
  replyMode = 'empty';
  await page.getByRole('button', { name: '刷新', exact: true }).click();
  await page.getByText('暂无最近进展。', { exact: true }).waitFor();
  for (const tab of ['总览', '记忆', '人物', '思考', '路线图']) {
    await page.getByRole('button', { name: tab, exact: true }).click();
    snapshots.push(await snapshot(page, `empty-${tab}`));
  }
  replyMode = 'failure';
  await page.getByRole('button', { name: '刷新', exact: true }).click();
  await page.locator('.error-text').waitFor();
  snapshots.push(await snapshot(page, 'network-error'));
  replyMode = 'fixture';
  await page.reload();
  await page.getByText('固定进展', { exact: true }).waitFor();
  await page.getByLabel('Dashboard token').fill('');
  assert.equal(await page.evaluate(() => localStorage.getItem('mako.dashboard.token')), null);
  await page.getByRole('button', { name: '刷新', exact: true }).click();
  await page.locator('.error-text').waitFor();
  snapshots.push(await snapshot(page, 'clear-token'));
  assert.deepEqual(errors, []);
  assert.deepEqual(forbidden, []);
  const csp = await page.evaluate(() => window.cspViolations);
  await context.close();
  return { snapshots, requests, csp };
}

(async () => {
  const browser = await chromium.launch({
    headless: true,
    ...(process.env.MAKO_TEST_BROWSER_CHANNEL ? { channel: process.env.MAKO_TEST_BROWSER_CHANNEL } : {})
  });
  const report = [];
  try {
    for (const width of [1360, 390]) {
      const before = await exercise(browser, true, width);
      const after = await exercise(browser, false, width);
      assert.deepEqual(after.requests, before.requests);
      assert.deepEqual(after.csp, before.csp);
      for (let i = 0; i < before.snapshots.length; i++) {
        assert.deepEqual(after.snapshots[i], before.snapshots[i], `${phase} width=${width} ${before.snapshots[i].label}`);
      }
      report.push({ width, states: after.snapshots.map(s => ({ label: s.label, hash: digest(s), overflow: s.size[0] > s.size[1] })), csp: after.csp });
      console.log(`PASS ${phase} ${width}px: ${after.snapshots.length} DOM/layout states, auth, navigation, search, filtering, empty/error, escaping, CSP parity`);
    }
    fs.writeFileSync(path.join(output, `${phase}-browser.json`), JSON.stringify(report, null, 2) + '\n');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
