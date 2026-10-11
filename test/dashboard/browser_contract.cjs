/* Optional: node test/dashboard/browser_contract.cjs; requires Playwright + Chromium/Edge.
 * All requests are intercepted. Optional screenshots use synthetic fixtures only.
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
  people: [{ id: 'p1', name: 'Fixture person', profile_text: 'Fixture preference', relationship_memories: [],
    ledger: { mode: '历史档案，暂停使用', persistence: 'Redis 已确认' } }],
  memory_persistence: 'Redis 已确认',
  companion: { available: true, enabled: true, persistence: 'Redis 已确认', items: [
    { plan_id: 'exam-synthetic', user_id: 101, revision: 3, status: 'active', title: dangerous,
      tasks: ['复习章节'], exam: '2026-10-09T15:00+08:00', reminder_time: '2026-10-09T13:00+08:00',
      consent: 'granted', review_time: '2026-10-09T16:00+08:00',
      reminder: { business: 'blocked', transport: 'unknown', effects: '待核对', reason: '存储待确认' },
      invitation: { business: 'blocked', transport: '尚未开始', effects: '尚未开始', reason: '考前提醒未确认' } },
    { plan_id: 'exam-forgotten', user_id: 102, revision: 4, status: 'forgotten', title: '', tasks: [],
      consent: 'revoked', reminder: { business: 'cancelled', transport: 'sent', effects: '待核对' },
      invitation: { business: 'cancelled', transport: '尚未开始', effects: '尚未开始' } }
  ] },
  relationship_memories: [{ id: 'm1', memory_id: 'm1', content: 'Fixture memory', status: 'active',
    source_excerpt: dangerous, evidence_kind: 'explicit', source_ref: { occurred_at: '2026-10-09', received_at: '2026-10-09' },
    ledger: { mode: '账本优先；旧画像暂停使用', persistence: 'Redis 已确认' }, confidence_label: '规则置信值，未经准确率校准' },
    { id: 'm2', memory_id: 'm2', content: '', status: 'forgotten', evidence_kind: 'legacy_unknown', source_excerpt: '', source_ref: {} }],
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
      if (url.pathname === '/mako/dashboard/api/group-rhythm') {
        if (route.request().headers().authorization !== 'Bearer synthetic-good') {
          return route.fulfill({ status: 401, contentType: 'application/json', body: '{}' });
        }
        if (replyMode === 'failure') return route.abort('failed');
        const items = replyMode === 'empty' ? [] : [
          { action: 'ignore', reason_label: dangerous, stage: 'finished', send_state: 'not_started', group_alias: 'g-synthetic', target_alias: 'm-ignore' },
          { action: 'wait', reason_label: '合并连续消息', wait_ms: 800, stage: 'waiting', send_state: 'not_started' },
          { action: 'reply', reason_label: '明确呼叫', stage: 'canceled', send_state: 'unknown', late_cancel: true, outcome_reason_label: '问题已由他人引用回答' }
        ].map((item, index) => ({
          trace_id: `trace-${index}`, group_alias: 'g-synthetic', target_alias: `m-${index}`,
          observed_at: '2026-10-09T00:00:00Z', updated_at: '2026-10-09T00:00:01Z',
          action: null, reason_code: null, reason_label: null, wait_ms: null,
          stage: 'observed', send_state: 'not_started', outcome_reason_code: null,
          outcome_reason_label: null, late_cancel: false, ...item
        }));
        return route.fulfill({ status: 200, contentType: 'application/json',
          body: JSON.stringify({ ok: true, data: { source: 'runtime',
            process_started_at: '2026-10-09T00:00:00Z', retention_seconds: 1800, items } }) });
      }
      if (url.pathname === '/mako/dashboard/api/summary') {
        const authorization = route.request().headers().authorization;
        requests.push(authorization);
        if (authorization !== 'Bearer synthetic-good') {
          return route.fulfill({ status: 401, contentType: 'application/json', body: '{}' });
        }
        if (replyMode === 'failure') return route.abort('failed');
        return route.fulfill({ status: 200, contentType: 'application/json',
          body: JSON.stringify(replyMode === 'empty' ? { ok: true, data: {
            companion: { available: true, enabled: true, items: [] }
          } } : replyMode === 'paused' ? { ...fixture, data: { ...fixture.data, companion: {
            ...fixture.data.companion, enabled: false, reason: '插件未启用，自动动作暂停'
          } } } : fixture) });
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
    await page.getByRole('button', { name: '群聊节奏', exact: true }).click();
    await page.getByText('发送确认未知', { exact: false }).waitFor();
    for (const button of await page.locator('.nav-tabs button').all()) {
      const box = await button.boundingBox();
      assert.ok(box && box.x >= 0 && box.x + box.width <= width, 'navigation is clipped');
    }
    assert.equal(await page.locator('.view-stack img').count(), 0);
    assert.equal(await page.evaluate(() => window.injected), undefined);
    assert.ok((await page.locator('.view-stack').textContent()).includes(dangerous));
    assert.ok(!(await page.locator('.view-stack').textContent()).includes('undefined'));
    if (process.env.MAKO_TEST_SCREENSHOTS) await page.screenshot({
      path: path.join(process.env.MAKO_TEST_SCREENSHOTS, `rhythm-${width}.png`), fullPage: true
    });
    for (const tab of ['考试陪伴', '记忆', '人物', '思考', '路线图']) {
      await page.getByRole('button', { name: tab, exact: true }).click();
      if (tab === '考试陪伴') {
        assert.equal(await page.locator('.companion-card').count(), 2);
        assert.ok((await page.locator('.view-stack').textContent()).includes('自动重发已暂停'));
        assert.ok((await page.locator('.view-stack').textContent()).includes('个人正文已清空'));
        assert.equal(await page.locator('.view-stack img').count(), 0);
        assert.ok((await page.locator('.view-stack').textContent()).includes(dangerous));
        if (process.env.MAKO_TEST_SCREENSHOTS) await page.screenshot({
          path: path.join(process.env.MAKO_TEST_SCREENSHOTS, `companion-${width}.png`), fullPage: true
        });
      }
      if (tab === '记忆') {
        const details = page.locator('.view-stack .detail-card');
        await details.first().locator('summary').click();
        assert.ok((await page.locator('.view-stack').textContent()).includes('规则置信值，未经准确率校准'));
        assert.ok((await page.locator('.view-stack').textContent()).includes('已遗忘'));
        assert.ok((await page.locator('.view-stack').textContent()).includes('正文和来源片段已清空'));
        if (process.env.MAKO_TEST_SCREENSHOTS) await page.screenshot({
          path: path.join(process.env.MAKO_TEST_SCREENSHOTS, `ledger-${width}.png`), fullPage: true
        });
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
    await page.getByRole('button', { name: '群聊节奏', exact: true }).click();
    await page.getByText('暂无记录', { exact: true }).waitFor();
    await page.getByRole('button', { name: '考试陪伴', exact: true }).click();
    await page.getByText('暂无匹配的本人考试计划。', { exact: true }).waitFor();
    for (const tab of ['记忆', '人物', '思考', '路线图']) {
      await page.getByRole('button', { name: tab, exact: true }).click();
    }
    replyMode = 'failure';
    await page.getByRole('button', { name: '刷新', exact: true }).click();
    await page.locator('.error-text').waitFor();
    await page.getByRole('button', { name: '群聊节奏', exact: true }).click();
    assert.equal(await page.locator('.view-stack .error-text').count(), 1);
    assert.ok(!(await page.locator('.view-stack').textContent()).includes('暂无记录'));
    await page.getByRole('button', { name: '考试陪伴', exact: true }).click();
    assert.equal(await page.locator('.view-stack .error-text').count(), 1);
    assert.ok(!(await page.locator('.view-stack').textContent()).includes('暂无匹配的本人考试计划'));
    replyMode = 'paused';
    await page.getByRole('button', { name: '刷新', exact: true }).click();
    await page.getByText('插件未启用，自动动作暂停', { exact: true }).waitFor();
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
