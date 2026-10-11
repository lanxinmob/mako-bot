const API_URL = '/mako/dashboard/api/summary';

export async function requestSummary(token) {
  const response = await fetch(API_URL, { headers: { Authorization: `Bearer ${token}` } });
  if (!response.ok) throw new Error(`工作台读取失败：HTTP ${response.status}`);
  return response.json();
}

export async function requestRhythm(token) {
  const response = await fetch('/mako/dashboard/api/group-rhythm?limit=50', {
    headers: { Authorization: `Bearer ${token}` }
  });
  if (!response.ok) throw new Error(`群聊节奏读取失败：HTTP ${response.status}`);
  const payload = await response.json();
  if (payload?.ok !== true || payload?.data?.source !== 'runtime' || !Array.isArray(payload.data.items)) {
    throw new Error('群聊节奏返回了无效状态');
  }
  return payload.data;
}
