/* Optional: node test/dashboard/browser_contract.cjs; requires Playwright + Chromium/Edge.
 * All requests are intercepted. Uses current assets; no Git history or screenshots.
 */
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

const assets = path.resolve(__dirname, '../../src/web/dashboard/static');
const headers = {
  'Content-Security-Policy': "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'",
  'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer', 'X-Content-Type-Options': 'nosniff'
};
const dangerous = '<img src="https://external.invalid/never" onerror="window.injected=true">';
const tasks = ['done', 'doing', 'blocked', 'todo'].map((status, index) => ({
  id: `t-${index}`, title: `Task ${index}`, summary: 'Fixture task', status,
  completion_criteria: ['Verified result'], completion_basis: ['Fixture evidence'],
  why_status: 'Fixture status', verification: 'Offline check', next_step: 'Next step', children: []
}));
const fixture = { ok: true, data: {
  progress: { percent: 25, updated_at: '2026-01-02 03:04', streak: 'Fixture progress' },
  recent_progress: [{ time: '03:04', title: 'Latest event' }],
  mako_profile: { name: 'Mako', summary: 'Fixture profile', values: ['Boundaries'] },
  notes: [{ id: 'n1', title: 'Fixture note', content: dangerous }],
  people: [{ id: 'p1', name: 'Fixture person', profile_text: 'Fixture preference', relationship_memories: [] }],
  relationship_memories: [{ id: 'm1', content: 'Fixture memory' }],
  thought_traces: [{ id: 'trace', title: 'Fixture trace', summary: 'Fixture audit', payload: { action: 'silent' } }],
  roadmap_tasks: tasks, roadmap_groups: [{ id: 'g1', title: 'Fixture roadmap', tasks }]
} };

async function exercise(browser, width) {
  const context = await browser.newContext({ viewport: { width, height: 900 } });
  try {
    const page = await context.newPage();
    const errors = [], forbidden = [], requests = [];
    let replyMode = 'fixture';
    page.on('pageerror', error => errors.push(error.message));
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
        return route.fulfill({ status: 200, contentType: 'application/json',
          body: JSON.stringify(replyMode === 'empty' ? {} : fixture) });
      }
      const relative = url.pathname === '/mako/dashboard' ? 'index.html' : url.pathname.replace('/mako/dashboard/', '');
      const target = path.resolve(assets, relative);
      if (!target.startsWith(assets + path.sep) || !fs.existsSync(target) || !fs.statSync(target).isFile()) {
        forbidden.push(url.href);
        return route.abort();
      }
      const contentType = relative.endsWith('.js') ? 'text/javascript' : relative.endsWith('.css') ? 'text/css' : 'text/html';
      return route.fulfill({ status: 200, headers, contentType, body: fs.readFileSync(target, 'utf8') });
    });
    await page.goto('http://dashboard.test/mako/dashboard?token=ignored');
    await page.locator('.error-text').waitFor();
    assert.equal(requests.length, 0);
    await page.getByLabel('Dashboard token').fill(' synthetic-wrong ');
    await page.getByRole('button', { name: '刷新', exact: true }).click();
    await page.getByText('工作台读取失败：HTTP 401', { exact: true }).waitFor();
    await page.getByLabel('Dashboard token').fill(' synthetic-good ');
    await page.getByRole('button', { name: '刷新', exact: true }).click();
    await page.getByText('Latest event', { exact: true }).waitFor();
    assert.equal(await page.evaluate(() => localStorage.getItem('mako.dashboard.token')), 'synthetic-good');
    for (const tab of ['记忆', '人物', '思考', '路线图']) {
      await page.getByRole('button', { name: tab, exact: true }).click();
      if (tab === '记忆') {
        assert.equal(await page.locator('.view-stack img').count(), 0);
        assert.equal(await page.evaluate(() => window.injected), undefined);
        assert.ok((await page.locator('.view-stack').textContent()).includes(dangerous));
      }
      if (tab === '人物' || tab === '思考') await page.locator('details summary').first().click();
    }
    await page.getByRole('combobox').selectOption('done');
    assert.equal(await page.locator('.task-card').count(), 1);
    await page.locator('.task-card summary').click();
    const search = page.getByPlaceholder('搜索笔记、人物、任务、思考');
    await search.fill('no-such-fixture');
    await page.getByText('没有匹配当前筛选的任务。', { exact: true }).waitFor();
    await search.fill('');
    await page.getByRole('combobox').selectOption('all');
    replyMode = 'empty';
    await page.getByRole('button', { name: '总览', exact: true }).click();
    await page.getByRole('button', { name: '刷新', exact: true }).click();
    await page.getByText('暂无最近进展。', { exact: true }).waitFor();
    for (const tab of ['记忆', '人物', '思考', '路线图']) {
      await page.getByRole('button', { name: tab, exact: true }).click();
    }
    replyMode = 'failure';
    await page.getByRole('button', { name: '刷新', exact: true }).click();
    await page.locator('.error-text').waitFor();
    replyMode = 'fixture';
    await page.reload();
    await page.getByText('Latest event', { exact: true }).waitFor();
    await page.getByLabel('Dashboard token').fill('');
    assert.equal(await page.evaluate(() => localStorage.getItem('mako.dashboard.token')), null);
    const before = requests.length;
    await page.getByRole('button', { name: '刷新', exact: true }).click();
    await page.locator('.error-text').waitFor();
    assert.equal(requests.length, before);
    assert.deepEqual(errors, []);
    assert.deepEqual(forbidden, []);
    console.log(`PASS ${width}px: token, escaping, navigation, filters, empty/error states`);
  } finally {
    await context.close();
  }
}

(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.MAKO_TEST_BROWSER_CHANNEL ? { channel: process.env.MAKO_TEST_BROWSER_CHANNEL } : {}) });
  try {
    for (const width of [1360, 390]) await exercise(browser, width);
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
