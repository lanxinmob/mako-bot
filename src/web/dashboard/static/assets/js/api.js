const API_URL = '/mako/dashboard/api/summary';

export async function requestSummary(token) {
  const response = await fetch(API_URL, { headers: { Authorization: `Bearer ${token}` } });
  if (!response.ok) throw new Error(`工作台读取失败：HTTP ${response.status}`);
  return response.json();
}
