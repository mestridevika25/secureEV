import React from 'react';

export const ECU_ORDER = ['VCU', 'BMS', 'BCM', 'MCU', 'TCU', 'ACU', 'CHG', 'CAM', 'OTA'];

export function MetricCard({ label, value, unit = '', meta = '' }) {
  return (
    <div className="metric-card">
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value ?? '—'} <span>{unit}</span></div>
      {meta ? <div className="metric-meta">{meta}</div> : null}
    </div>
  );
}

export function StatusDot({ online = false }) {
  return <span className={`status-dot ${online ? 'online' : 'offline'}`} />;
}

export function EcuGrid({ ecus = {} }) {
  return (
    <div className="ecu-grid">
      {ECU_ORDER.map((ecu) => {
        const status = ecus[ecu] || 'OFFLINE';
        const online = String(status).toUpperCase() === 'ONLINE';
        return (
          <div className="ecu-card" key={ecu}>
            <div className="ecu-name">{ecu}</div>
            <div className="ecu-status"><StatusDot online={online} />{status}</div>
          </div>
        );
      })}
    </div>
  );
}

export function Sparkline({ values = [], label }) {
  const width = 320;
  const height = 90;
  const padding = 8;
  if (!values.length) return <div className="sparkline-empty">Waiting for {label.toLowerCase()} telemetry…</div>;

  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const points = values.map((v, i) => {
    const x = padding + (i / Math.max(values.length - 1, 1)) * (width - padding * 2);
    const y = height - padding - ((v - min) / range) * (height - padding * 2);
    return `${x},${y}`;
  }).join(' ');

  return (
    <div className="sparkline-wrap">
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" aria-label={`${label} history`}>
        <polyline points={points} fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" />
      </svg>
      <div className="sparkline-range"><span>{min.toFixed(1)}</span><span>{max.toFixed(1)}</span></div>
    </div>
  );
}

export function AlertRow({ alert }) {
  const severity = String(alert.severity || 'INFO').toUpperCase();
  const title = String(alert.attack_type || alert.event_type || 'Security event').replaceAll('_', ' ');
  return (
    <div className={`alert-row severity-${severity.toLowerCase()}`}>
      <div className="alert-icon">{severity === 'CRITICAL' ? '!' : severity === 'HIGH' ? '⚠' : 'i'}</div>
      <div>
        <div className="alert-title">{title}</div>
        <div className="alert-meta">{alert.ecu || 'SYSTEM'} · {severity} · {alert.reason || alert.action || 'Event recorded'}</div>
      </div>
      <div className="alert-time">{formatTime(alert.timestamp)}</div>
    </div>
  );
}

export function HistoryTable({ attacks = [], responses = [], recoveries = [] }) {
  const items = [
    ...attacks.map((a) => ({ time: a.recorded_at, kind: 'ATTACK', name: a.name, ecu: a.target_ecu, status: a.status })),
    ...responses.map((r) => ({ time: r.recorded_at, kind: 'RESPONSE', name: r.action, ecu: r.ecu, status: r.executed ? 'EXECUTED' : 'FAILED' })),
    ...recoveries.map((r) => ({ time: r.recorded_at, kind: 'RECOVERY', name: 'safe baseline restore', ecu: r.vehicle_id, status: r.status })),
  ].sort((a, b) => new Date(b.time) - new Date(a.time)).slice(0, 20);

  if (!items.length) return <div className="empty-state">No security history recorded yet.</div>;

  return (
    <div className="table-wrap">
      <table>
        <thead><tr><th>Time</th><th>Type</th><th>Event</th><th>Target</th><th>Status</th></tr></thead>
        <tbody>
          {items.map((item, index) => (
            <tr key={`${item.kind}-${item.time}-${index}`}>
              <td>{formatDateTime(item.time)}</td>
              <td><span className={`pill ${item.kind === 'ATTACK' ? 'pill-warn' : item.kind === 'RECOVERY' ? 'pill-info' : 'pill-ok'}`}>{item.kind}</span></td>
              <td>{String(item.name).replaceAll('_', ' ')}</td>
              <td>{item.ecu || '—'}</td>
              <td>{item.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function formatTime(value) {
  if (!value) return '—';
  return new Date(Number(value) * 1000).toLocaleTimeString();
}

function formatDateTime(value) {
  if (!value) return '—';
  return new Date(value).toLocaleString();
}
