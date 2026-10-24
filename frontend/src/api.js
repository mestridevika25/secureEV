const API_BASE = (import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...(options.headers || {}),
    },
  });

  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      // Keep the status text.
    }
    throw new Error(detail);
  }
  return response.json();
}

export const api = {
  getSnapshot: () => request('/snapshot'),
  getHealth: () => request('/health'),
  getSummary: () => request('/reports/summary'),
  getEvaluation: () => request('/reports/evaluation'),
  getSecurityAlerts: () => request('/security/alerts?limit=50'),
  getAttacks: () => request('/history/attacks?limit=50'),
  getResponses: () => request('/history/responses?limit=50'),
  getSecurityHistory: () => request('/history/security?limit=100'),
  getRecoveryHistory: () => request('/history/recovery?limit=50'),
  startRuntime: () => request('/runtime/start', { method: 'POST' }),
  stopRuntime: () => request('/runtime/stop', { method: 'POST' }),
  recoverRuntime: () => request('/runtime/recover', { method: 'POST' }),
  startCamera: () => request('/camera/start', { method: 'POST' }),
  stopCamera: () => request('/camera/stop', { method: 'POST' }),
  emergencyBrake: () => request('/vehicle/emergency-brake', { method: 'POST' }),
  startAutonomous: (targetSpeedKmh = 28) => request('/vehicle/autonomous/start', { method: 'POST', body: JSON.stringify({ target_speed_kmh: targetSpeedKmh }) }),
  stopAutonomous: () => request('/vehicle/autonomous/stop', { method: 'POST' }),
  replanAutonomous: () => request('/vehicle/autonomous/replan', { method: 'POST' }),
  vehicleControl: (control) => request('/vehicle/control', {
    method: 'POST',
    body: JSON.stringify(control),
  }),
  launchAttack: (name) => request('/attacks/launch', {
    method: 'POST',
    body: JSON.stringify({ name }),
  }),
};

export function websocketUrl() {
  const url = new URL(API_BASE);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  url.pathname = '/ws/live';
  url.search = '';
  url.hash = '';
  return url.toString();
}

export function cameraMjpegUrl(cacheKey = '') {
  return `${API_BASE}/camera/mjpeg${cacheKey ? `?stream=${encodeURIComponent(cacheKey)}` : ''}`;
}

export function reportUrl(kind) {
  return `${API_BASE}/reports/export.${kind}`;
}
