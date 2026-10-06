import { state, fallbackSummary, TOKEN_KEY } from './state.js';
import { normalizeSummary } from './format.js';
import { requestSummary } from './api.js';

export function createEvents(render) {
  async function loadSummary() {
    if (!state.token) {
      state.error = '请输入 Dashboard token；它只会保存在当前浏览器的 localStorage 中。';
      state.summary = fallbackSummary;
      render();
      return;
    }
    state.loading = true;
    state.error = '';
    render();
    try {
      const payload = await requestSummary(state.token);
      state.summary = normalizeSummary(payload);
    } catch (error) {
      state.summary = fallbackSummary;
      state.error = error.message || '工作台读取失败';
    } finally {
      state.loading = false;
      render();
    }
  }

  return {
    loadSummary,
    setActive(key) { state.active = key; render(); },
    onTokenInput(event) {
      state.token = event.target.value.trim();
      if (state.token) localStorage.setItem(TOKEN_KEY, state.token);
      else localStorage.removeItem(TOKEN_KEY);
    },
    onQueryInput(event) { state.query = event.target.value; render(); },
    onStatusChange(event) { state.status = event.target.value; render(); }
  };
}
