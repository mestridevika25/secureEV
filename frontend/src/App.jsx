import React, { useEffect, useMemo, useRef, useState } from 'react';
import { api, cameraMjpegUrl, reportUrl, websocketUrl } from './api';
import { AlertRow, EcuGrid, HistoryTable, MetricCard, Sparkline, StatusDot } from './components';

const HISTORY_LIMIT = 50;
const ATTACKS = [
  { name: 'gps_spoofing', label: 'GPS Spoofing', target: 'TCU', kind: 'Telemetry', description: 'Inject false GPS telemetry and compare the reported position against CARLA ground truth.' },
  { name: 'battery_soc_spoofing', label: 'Battery SOC Spoofing', target: 'BMS', kind: 'Telemetry', description: 'Inject false battery state-of-charge telemetry and compare it against the trusted Digital Twin value.' },
  { name: 'unauthorized_acceleration', label: 'Unauthorized Acceleration', target: 'VCU', kind: 'Control', description: 'Simulate an unauthorized acceleration command and display its actual execution, detection, and response outcome.' },
];

const SUPPORTED_ATTACKS = new Set(ATTACKS.map((attack) => attack.name));

function attackLabel(name) {
  return String(name || 'Unknown attack').replaceAll('_', ' ');
}

function attackObservedEffect(attack) {
  const details = attack?.details || attack || {};
  return details.observed_effect || details.attack_effect || details.description || 'Unknown';
}

function attackDetection(attack) {
  if (typeof attack?.detected === 'boolean') return attack.detected ? 'DETECTED' : 'NOT DETECTED';
  if (typeof attack?.details?.detected === 'boolean') return attack.details.detected ? 'DETECTED' : 'NOT DETECTED';
  return 'Unknown';
}

function attackResponse(attack) {
  const details = attack?.details || attack || {};
  if (details.response_status) return details.response_status;
  if (details.response_executed === true) return 'RESPONSE EXECUTED';
  if (details.response_executed === false) return 'RESPONSE FAILED';
  return 'Unknown';
}

function supportedAttacks(attacks) {
  return (Array.isArray(attacks) ? attacks : [])
    .filter((attack) => SUPPORTED_ATTACKS.has(attack.name))
    .sort((a, b) => new Date(b.recorded_at || b.timestamp || 0) - new Date(a.recorded_at || a.timestamp || 0));
}

const emptySnapshot = {
  runtime: { running: false, ecu_status: {}, control_bridge: {}, response: {}, integrity: { firmware_signature_configured: false, untrusted_ecus: [] }, camera: {}, autonomy: { enabled: false, mode: 'MANUAL', target_speed_kmh: 28, next_maneuver: null } },
  vehicle: {
    id: 'SEV-001', status: 'OFFLINE', speed_kmh: 0, acceleration_mps2: 0,
    battery_soc: 0, battery_temp: 0, motor_rpm: 0, motor_temp: 0,
    doors_locked: true, doors_open: false, reported_gps: {}, autonomous_mode: false,
    charging_state: 'idle', charge_port_locked: true, camera_feed_source: 'live', firmware_version: '1.0.0', ground_truth: {},
  },
  ecus: {}, telemetry: {}, security: { risk: { score: 0, level: 'LOW', critical: 0, high: 0 }, alerts: [], recent_events: [] },
  attacks: [], responses: [], recovery: [],
};

export default function App() {
  const [snapshot, setSnapshot] = useState(emptySnapshot);
  const [connected, setConnected] = useState(false);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [control, setControl] = useState({ throttle: 0, brake: 0, steer: 0 });
  const [patrolSpeed, setPatrolSpeed] = useState(28);
  const [speedHistory, setSpeedHistory] = useState([]);
  const [batteryHistory, setBatteryHistory] = useState([]);
  const [history, setHistory] = useState({ attacks: [], responses: [], recoveries: [] });
  const [evaluation, setEvaluation] = useState(null);
  const [activeView, setActiveView] = useState('overview');
  const [cameraNonce, setCameraNonce] = useState(Date.now());
  const reconnectTimer = useRef(null);

  useEffect(() => {
    let ws;
    let closed = false;

    const connect = () => {
      try {
        ws = new WebSocket(websocketUrl());
        ws.onopen = () => setConnected(true);
        ws.onmessage = (event) => {
          try {
            const next = JSON.parse(event.data);
            setSnapshot(next);
            setSpeedHistory((prev) => [...prev, Number(next.vehicle?.speed_kmh || 0)].slice(-HISTORY_LIMIT));
            setBatteryHistory((prev) => [...prev, Number(next.vehicle?.battery_soc || 0)].slice(-HISTORY_LIMIT));
          } catch {
            // Ignore malformed websocket payloads.
          }
        };
        ws.onerror = () => setConnected(false);
        ws.onclose = () => {
          setConnected(false);
          if (!closed) reconnectTimer.current = setTimeout(connect, 1200);
        };
      } catch {
        setConnected(false);
        if (!closed) reconnectTimer.current = setTimeout(connect, 1200);
      }
    };

    connect();
    return () => {
      closed = true;
      clearTimeout(reconnectTimer.current);
      ws?.close();
    };
  }, []);

  useEffect(() => {
    const loadHistory = async () => {
      try {
        const [attacks, responses, recoveries, report] = await Promise.all([
          api.getAttacks(), api.getResponses(), api.getRecoveryHistory(), api.getEvaluation(),
        ]);
        setHistory({
          attacks: Array.isArray(attacks) ? attacks : [],
          responses: Array.isArray(responses) ? responses : [],
          recoveries: Array.isArray(recoveries) ? recoveries : [],
        });
        setEvaluation(report);
      } catch {
        // The live websocket remains the primary source of truth while online.
      }
    };
    loadHistory();
    const timer = setInterval(loadHistory, 5000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!message) return undefined;
    const timer = setTimeout(() => setMessage(''), 3500);
    return () => clearTimeout(timer);
  }, [message]);

  const vehicle = snapshot.vehicle || emptySnapshot.vehicle;
  const risk = snapshot.security?.risk || emptySnapshot.security.risk;
  const alerts = snapshot.security?.alerts || [];
  const ecuStatus = snapshot.ecus || {};
  const isRunning = Boolean(snapshot.runtime?.running);
  const onlineCount = useMemo(() => Object.values(ecuStatus).filter((status) => status === 'ONLINE').length, [ecuStatus]);
  const latestAttack = supportedAttacks(snapshot.attacks).at(0);
  const latestResponse = snapshot.responses?.[snapshot.responses.length - 1];
  const latestRecovery = snapshot.recovery?.[snapshot.recovery.length - 1];
  const cameraAttached = Boolean(snapshot.runtime?.camera?.attached);
  const autonomy = snapshot.runtime?.autonomy || { enabled: false, mode: 'MANUAL', target_speed_kmh: patrolSpeed, next_maneuver: null };
  const autonomous = Boolean(autonomy.enabled || vehicle.autonomous_mode);

  const action = async (fn, successMessage, refreshCamera = false) => {
    if (busy) return;
    setBusy(true);
    try {
      const result = await fn();
      setMessage(result?.error ? `Request failed: ${result.error}` : successMessage);
      const fresh = await api.getSnapshot();
      setSnapshot(fresh);
      if (refreshCamera) setCameraNonce(Date.now());
      const [attacks, responses, recoveries, report] = await Promise.all([
        api.getAttacks(), api.getResponses(), api.getRecoveryHistory(), api.getEvaluation(),
      ]);
      setHistory({ attacks, responses, recoveries });
      setEvaluation(report);
    } catch (error) {
      setMessage(error.message || 'Request failed');
    } finally {
      setBusy(false);
    }
  };

  const toggleCamera = () => {
    if (cameraAttached) return action(() => api.stopCamera(), 'CARLA camera disabled.');
    return action(() => api.startCamera(), 'CARLA camera enabled.', true);
  };

  const launchAttack = (name) => action(() => api.launchAttack(name), `${name.replaceAll('_', ' ')} published.`);
  const sendControl = () => action(() => api.vehicleControl(control), 'VCU command sent through MQTT.');
  const neutral = () => action(() => api.vehicleControl({ throttle: 0, brake: 0, steer: 0 }), 'Vehicle control set to neutral.');
  const startPatrol = () => action(() => api.startAutonomous(patrolSpeed), `Autonomous patrol started at ${patrolSpeed} km/h.`);
  const stopPatrol = () => action(() => api.stopAutonomous(), 'Switched to manual mode.');
  const replanPatrol = () => action(() => api.replanAutonomous(), 'Autonomous route replanned.');

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-block">
          <div className="brand-mark">SEV</div>
          <div><div className="brand-title">SecureEV</div><div className="brand-subtitle">Connected EV security testbed</div></div>
        </div>
        <div className="top-actions">
          <div className="connection-badge"><StatusDot online={connected} /> WebSocket {connected ? 'LIVE' : 'RECONNECTING'}</div>
          <div className="vehicle-badge">Vehicle <strong>{vehicle.id}</strong></div>
          <div className={`risk-badge risk-${String(risk.level).toLowerCase()}`}>Risk {risk.score}/100 · {risk.level}</div>
        </div>
      </header>

      <nav className="nav-tabs">
        {['overview', 'security', 'history', 'reports'].map((view) => (
          <button key={view} className={activeView === view ? 'active' : ''} onClick={() => setActiveView(view)}>{view[0].toUpperCase() + view.slice(1)}</button>
        ))}
      </nav>

      {message ? <div className="toast">{message}</div> : null}

      <main className="content">
        <section className="status-strip">
          <div><span className={`system-state ${isRunning ? 'good' : 'offline'}`}>{isRunning ? 'SYSTEM ONLINE' : 'SYSTEM OFFLINE'}</span></div>
          <div>ECUs online <strong>{onlineCount}/9</strong></div>
          <div>Active alerts <strong>{alerts.length}</strong></div>
          <div>Last response <strong>{latestResponse?.action || 'None'}</strong></div>
          <div>Mode <strong>{autonomous ? 'AUTONOMOUS' : 'MANUAL'}</strong>{autonomy.next_maneuver ? ` · ${autonomy.next_maneuver}` : ''}</div>
        </section>

        {activeView === 'overview' ? (
          <>
            <section className="metric-grid">
              <MetricCard
                label="Speed"
                value={Number(vehicle.trusted_speed_kmh ?? vehicle.speed_kmh ?? 0).toFixed(1)}
                unit="km/h"
                meta={`Reported ${Number(vehicle.reported_speed_kmh ?? vehicle.speed_kmh ?? 0).toFixed(1)} · Acceleration ${Number(vehicle.acceleration_mps2 || 0).toFixed(2)} m/s²`}
              />
              <MetricCard label="Battery" value={Number(vehicle.battery_soc || 0).toFixed(1)} unit="%" meta={`Temp ${Number(vehicle.battery_temp || 0).toFixed(1)} °C`} />
              <MetricCard label="Motor" value={Math.round(vehicle.motor_rpm || 0).toLocaleString()} unit="RPM" meta={`Temp ${Number(vehicle.motor_temp || 0).toFixed(1)} °C`} />
              <MetricCard label="GPS" value={vehicle.reported_gps?.source || '—'} meta={`${Number(vehicle.reported_gps?.x || 0).toFixed(2)}, ${Number(vehicle.reported_gps?.y || 0).toFixed(2)}`} />
            </section>

            <section className="two-column">
              <div className="panel panel-camera">
                <div className="panel-header">
                  <div><h2>Live CARLA camera</h2><p>Optional low-resolution RGB sensor feed</p></div>
                  <div className="panel-actions">
                    <span className={`live-chip ${cameraAttached ? '' : 'muted-chip'}`}>{cameraAttached ? 'LIVE' : 'DISABLED'}</span>
                    {isRunning ? <button className="btn secondary small" disabled={busy} onClick={toggleCamera}>{cameraAttached ? 'Disable' : 'Enable'}</button> : null}
                  </div>
                </div>
                <div className="camera-frame">
                  {isRunning && cameraAttached ? <img src={cameraMjpegUrl(cameraNonce)} alt="Live SecureEV CARLA camera" /> : <div className="camera-placeholder"><div className="camera-icon">◉</div><strong>{isRunning ? 'Camera disabled' : 'Camera unavailable'}</strong><span>{isRunning ? 'Keep the camera disabled for maximum CARLA stability. Enable it only when your GPU is stable.' : 'Start SecureEV to enable the optional CARLA RGB camera.'}</span></div>}
                </div>
              </div>

              <div className="panel">
                <div className="panel-header"><div><h2>ECU health</h2><p>Current subsystem status</p></div><span>{onlineCount}/9 online</span></div>
                <EcuGrid ecus={ecuStatus} />
              </div>
            </section>

            <section className="two-column">
              <div className="panel panel-large">
                <div className="panel-header"><div><h2>Vehicle telemetry</h2><p>Live values from the SecureEV digital twin</p></div><span className="live-chip">LIVE</span></div>
                <div className="telemetry-layout">
                  <div className="vehicle-visual">
                    <div className="car-outline">🚗</div>
                    <div className="vehicle-meta">
                      <div><span>Doors</span><strong>{vehicle.doors_locked ? 'LOCKED' : 'UNLOCKED'}</strong></div>
                      <div><span>Mode</span><strong>{vehicle.autonomous_mode ? 'AUTONOMOUS' : 'MANUAL'}</strong></div>
                      <div><span>Charging</span><strong>{String(vehicle.charging_state || 'idle').toUpperCase()}</strong></div>
                      <div><span>Firmware</span><strong>{vehicle.firmware_version || '—'}</strong></div>
                    </div>
                  </div>
                  <div className="charts-column">
                    <div className="chart-card"><div className="chart-title">Speed history</div><Sparkline values={speedHistory} label="Speed" /></div>
                    <div className="chart-card"><div className="chart-title">Battery SOC history</div><Sparkline values={batteryHistory} label="Battery" /></div>
                  </div>
                </div>
              </div>

              <div className="panel">
                <div className="panel-header"><div><h2>Ground-truth position</h2><p>Trusted CARLA state vs TCU-reported position</p></div></div>
                <div className="detail-card position-card">
                  <div><span>Reported X</span><strong>{Number(vehicle.reported_gps?.x || 0).toFixed(2)}</strong></div>
                  <div><span>Reported Y</span><strong>{Number(vehicle.reported_gps?.y || 0).toFixed(2)}</strong></div>
                  <div><span>Ground-truth X</span><strong>{Number(vehicle.ground_truth?.location?.x || 0).toFixed(2)}</strong></div>
                  <div><span>Ground-truth Y</span><strong>{Number(vehicle.ground_truth?.location?.y || 0).toFixed(2)}</strong></div>
                  <div><span>Position source</span><strong>{vehicle.reported_gps?.source || '—'}</strong></div>
                  <div><span>Camera feed</span><strong>{String(vehicle.camera_feed_source || 'live').toUpperCase()}</strong></div>
                </div>
              </div>
            </section>

            <section className="two-column">
              <div className="panel">
                <div className="panel-header"><div><h2>Security status</h2><p>Current-session detections</p></div><div className={`big-risk risk-${String(risk.level).toLowerCase()}`}>{risk.score}</div></div>
                <div className="security-summary">
                  <div className="security-kpi"><span>Critical</span><strong>{risk.critical}</strong></div>
                  <div className="security-kpi"><span>High</span><strong>{risk.high}</strong></div>
                  <div className="security-kpi"><span>Alerts</span><strong>{alerts.length}</strong></div>
                  <div className="security-kpi"><span>Attacks</span><strong>{snapshot.attacks?.length || 0}</strong></div>
                </div>
                <div className="alert-list">{alerts.length ? alerts.slice(-5).reverse().map((a, i) => <AlertRow key={`${a.timestamp}-${i}`} alert={a} />) : <div className="empty-state">No active security alerts.</div>}</div>
              </div>

              <div className="panel">
                <div className="panel-header"><div><h2>Runtime & control</h2><p>Application and VCU controls</p></div></div>
                <div className="control-buttons">
                  {!isRunning ? <button className="btn primary" disabled={busy} onClick={() => action(api.startRuntime, 'SecureEV runtime started.', true)}>Start SecureEV</button> : <button className="btn secondary" disabled={busy} onClick={() => action(api.stopRuntime, 'SecureEV runtime stopped.', true)}>Stop SecureEV</button>}
                  <button className="btn danger" disabled={busy || !isRunning} onClick={() => action(api.emergencyBrake, 'Emergency brake command sent.')}>Emergency Brake</button>
                  <button className="btn secondary" disabled={busy || !isRunning} onClick={() => action(api.recoverRuntime, 'Vehicle recovered to the safe baseline.', true)}>Recover</button>
                  <button className="btn secondary" disabled={busy || !isRunning} onClick={neutral}>Neutral</button>
                </div>
                <div className="autonomy-box">
                  <div className="subsection-title">Autonomous city patrol</div>
                  <div className="autonomy-status">
                    <strong>{autonomous ? 'AUTONOMOUS PATROL' : 'MANUAL MODE'}</strong>
                    <span>{autonomy.next_maneuver ? `Next: ${autonomy.next_maneuver}` : 'Traffic Manager road navigation'}</span>
                  </div>
                  <label className="slider-row">
                    <span>PATROL</span>
                    <input type="range" min="15" max="45" step="1" value={patrolSpeed} onChange={(e) => setPatrolSpeed(Number(e.target.value))} />
                    <strong>{patrolSpeed} km/h</strong>
                  </label>
                  <div className="control-buttons">
                    <button className="btn primary" disabled={busy || !isRunning} onClick={startPatrol}>Start / Resume Patrol</button>
                    <button className="btn secondary" disabled={busy || !isRunning} onClick={replanPatrol}>Replan Route</button>
                    <button className="btn secondary" disabled={busy || !isRunning || !autonomous} onClick={stopPatrol}>Manual Mode</button>
                  </div>
                </div>
                <div className="subsection-title">Manual VCU control</div>
                {['throttle', 'brake', 'steer'].map((key) => (
                  <label className="slider-row" key={key}>
                    <span>{key.toUpperCase()}</span>
                    <input type="range" min={key === 'steer' ? -1 : 0} max="1" step="0.01" value={control[key]} onChange={(e) => setControl((prev) => ({ ...prev, [key]: Number(e.target.value) }))} />
                    <strong>{control[key].toFixed(2)}</strong>
                  </label>
                ))}
                <button className="btn primary full" disabled={busy || !isRunning} onClick={sendControl}>Apply VCU command</button>
              </div>
            </section>
          </>
        ) : null}

        {activeView === 'security' ? (
          <section className="security-view">
            <div className="panel">
              <div className="panel-header"><div><h2>Red Team attack console</h2><p>Controlled attacks against the isolated SecureEV simulation</p></div></div>
              <div className="comparison-notice">Run one of the three supported demonstrations. Results below reflect the recorded execution, detection, and response independently.</div>
              <div className="attack-grid">
                {ATTACKS.map((attack) => (
                  <div className="attack-card" key={attack.name}>
                    <div className="attack-name">{attack.label}</div>
                    <div className="attack-target">{attack.kind} · Target ECU: {attack.target}</div>
                    <div className="attack-description">{attack.description}</div>
                    <button className="btn danger full" disabled={busy || !isRunning} onClick={() => launchAttack(attack.name)}>{busy ? 'Running…' : 'Run Attack'}</button>
                  </div>
                ))}
              </div>
            </div>
            <div className="two-column">
            <div className="panel"><div className="panel-header"><div><h2>Latest attack</h2><p>Most recently requested supported scenario</p></div></div>{latestAttack ? <div className="detail-card"><div><span>Attack</span><strong>{attackLabel(latestAttack.name)}</strong></div><div><span>Target</span><strong>{latestAttack.ecu || latestAttack.target_ecu || 'Unknown'}</strong></div><div><span>Execution</span><strong>{latestAttack.published ? 'ATTACK EXECUTED' : 'RESPONSE FAILED'}</strong></div><div><span>Detection</span><strong>{attackDetection(latestAttack)}</strong></div><div><span>Observed effect</span><strong>{attackObservedEffect(latestAttack)}</strong></div></div> : <div className="empty-state">No supported attacks recorded.</div>}</div>
              <div className="panel"><div className="panel-header"><div><h2>Latest response</h2><p>Defensive action from the response engine</p></div></div>{latestResponse ? <div className="detail-card"><div><span>Action</span><strong>{latestResponse.action}</strong></div><div><span>ECU</span><strong>{latestResponse.ecu}</strong></div><div><span>Severity</span><strong>{latestResponse.severity}</strong></div></div> : <div className="empty-state">No response recorded.</div>}</div>
            </div>
            <div className="panel"><div className="panel-header"><div><h2>Security event stream</h2><p>Current and persisted security events</p></div></div><div className="alert-list">{snapshot.security?.recent_events?.length ? snapshot.security.recent_events.slice().reverse().map((a, i) => <AlertRow key={`${a.id || a.timestamp}-${i}`} alert={a} />) : <div className="empty-state">No security events.</div>}</div></div>
          </section>
        ) : null}

        {activeView === 'history' ? (
          <section className="history-view">
            <div className="panel"><div className="panel-header"><div><h2>Recent supported attacks</h2><p>Newest executions first</p></div></div><HistoryTable attacks={history.attacks} /></div>
          </section>
        ) : null}

        {activeView === 'reports' ? (
          <section className="reports-view">
            <div className="panel">
              <div className="panel-header"><div><h2>Security report</h2><p>Operational project metrics from the local SecureEV database</p></div></div>
              {evaluation ? (
                <div className="report-grid">
                  <MetricCard label="Supported attacks" value={evaluation.supported_attacks} />
                  <MetricCard label="GPS executions" value={evaluation.attack_counts?.gps_spoofing || 0} />
                  <MetricCard label="Battery SOC executions" value={evaluation.attack_counts?.battery_soc_spoofing || 0} />
                  <MetricCard label="Unauthorized acceleration" value={evaluation.attack_counts?.unauthorized_acceleration || 0} />
                  <MetricCard label="Confirmed detections" value={evaluation.supported_detections} />
                  <MetricCard label="Responses executed" value={evaluation.supported_responses_executed} />
                  <MetricCard label="Responses failed" value={evaluation.supported_responses_failed} />
                  <MetricCard label="Recoveries" value={evaluation.recovery_events} />
                </div>
              ) : <div className="empty-state">Loading evaluation…</div>}
              <div className="export-row">
                <a className="btn primary" href={reportUrl('json')} download="secureev_report.json">Export JSON</a>
                <a className="btn secondary" href={reportUrl('csv')} download="secureev_report.csv">Export CSV</a>
              </div>
              <div className="report-note">{evaluation?.note || 'Metrics are calculated from recorded project events.'}</div>
            </div>
            <div className="panel"><div className="panel-header"><div><h2>Recent outcomes</h2><p>Attack execution, detection, and response are separate facts.</p></div></div><HistoryTable attacks={history.attacks} /></div>
            <div className="panel"><div className="panel-header"><div><h2>Latest recovery</h2><p>Safe-state restoration status</p></div></div>{latestRecovery ? <div className="detail-card"><div><span>Status</span><strong>{latestRecovery.status}</strong></div><div><span>Vehicle</span><strong>{latestRecovery.vehicle_id}</strong></div><div><span>Restored</span><strong>{latestRecovery.restored_ecus?.length || 0} ECUs</strong></div></div> : <div className="empty-state">No recovery event recorded yet.</div>}</div>
          </section>
        ) : null}
      </main>
      <footer className="footer">SecureEV · academic cybersecurity testbed · FastAPI + WebSocket + MQTT + CARLA</footer>
    </div>
  );
}
