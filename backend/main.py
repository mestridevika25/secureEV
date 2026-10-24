"""FastAPI application for the SecureEV live dashboard."""

from __future__ import annotations

import asyncio
import csv
import io
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select

from backend.runtime import SecureEVRuntime
from database.db import SessionLocal, init_db
from database.models import (
    AttackRecord,
    RecoveryRecord,
    ResponseRecord,
    SecurityEventRecord,
    TelemetryRecord,
)

VEHICLE_ID = "SEV-001"


class ControlRequest(BaseModel):
    throttle: float = Field(default=0.0, ge=0.0, le=1.0)
    brake: float = Field(default=0.0, ge=0.0, le=1.0)
    steer: float = Field(default=0.0, ge=-1.0, le=1.0)

    @field_validator("throttle", "brake", "steer")
    @classmethod
    def finite_numbers(cls, value: float) -> float:
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("Control values must be finite numbers.")
        return value


class AttackRequest(BaseModel):
    name: str = Field(min_length=2, max_length=96)


class AutonomousRequest(BaseModel):
    target_speed_kmh: float = Field(default=28.0, ge=5.0, le=60.0)


class SecureEVService:
    """Application state shared by REST, WebSocket and database layers."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.runtime = SecureEVRuntime(event_callback=self.handle_runtime_event)
        self.current_telemetry: dict[str, dict[str, Any]] = {}
        self.alerts: list[dict[str, Any]] = []
        self.attack_history: list[dict[str, Any]] = []
        self.response_history: list[dict[str, Any]] = []
        self.security_events: list[dict[str, Any]] = []
        self.recovery_history: list[dict[str, Any]] = []
        self.max_history = 300
        self._last_db_telemetry_time: dict[str, float] = {}
        self.telemetry_db_interval = 1.0

    def hydrate_from_db(self) -> None:
        """Load persisted history without treating old alerts as active threats."""
        with self._lock, SessionLocal() as db:
            attacks = list(db.scalars(select(AttackRecord).order_by(AttackRecord.id.desc()).limit(self.max_history)))
            responses = list(db.scalars(select(ResponseRecord).order_by(ResponseRecord.id.desc()).limit(self.max_history)))
            security = list(db.scalars(select(SecurityEventRecord).order_by(SecurityEventRecord.id.desc()).limit(self.max_history)))
            recovery = list(db.scalars(select(RecoveryRecord).order_by(RecoveryRecord.id.desc()).limit(self.max_history)))

            self.attack_history = [
                {
                    "id": row.id,
                    "recorded_at": row.recorded_at.isoformat() if row.recorded_at else None,
                    "name": row.name,
                    "target_ecu": row.target_ecu,
                    "topic": row.topic,
                    "status": row.status,
                    "description": row.description,
                    "details": row.details,
                    **((row.details or {}).copy() if isinstance(row.details, dict) else {}),
                }
                for row in reversed(attacks)
            ]
            self.response_history = [
                {
                    "id": row.id,
                    "recorded_at": row.recorded_at.isoformat() if row.recorded_at else None,
                    "action": row.action,
                    "ecu": row.ecu,
                    "attack_type": row.attack_type,
                    "severity": row.severity,
                    "executed": row.executed,
                    "reason": row.reason,
                }
                for row in reversed(responses)
            ]
            self.security_events = [self._security_row(row) for row in reversed(security)]
            self.alerts = []
            self.recovery_history = [
                {
                    "id": row.id,
                    "recorded_at": row.recorded_at.isoformat() if row.recorded_at else None,
                    "vehicle_id": row.vehicle_id,
                    "status": row.status,
                    "restored_ecus": row.restored_ecus,
                    "details": row.details,
                }
                for row in reversed(recovery)
            ]

    @staticmethod
    def _security_row(row: SecurityEventRecord) -> dict[str, Any]:
        details = row.details or {}
        return {
            "id": row.id,
            "timestamp": details.get("timestamp") or time.time(),
            "recorded_at": row.recorded_at.isoformat() if row.recorded_at else None,
            "type": "security_event",
            "event_type": row.event_type,
            "severity": row.severity,
            "ecu": row.ecu,
            "attack_type": row.attack_type,
            "action": row.action,
            "reason": row.reason,
            "details": details,
        }

    def _append(self, target: list[dict[str, Any]], item: dict[str, Any]) -> None:
        with self._lock:
            target.append(dict(item))
            if len(target) > self.max_history:
                del target[:-self.max_history]

    def handle_runtime_event(self, event: dict[str, Any]) -> None:
        event_type = event.get("type")
        if event_type == "telemetry":
            self.record_telemetry(str(event.get("topic", "")), dict(event.get("payload") or {}))
            return

        if event_type == "security_gateway":
            severity = "HIGH" if event.get("action") == "BLOCK" else "INFO"
            item = {
                **event,
                "type": "security_event",
                "event_type": "gateway",
                "severity": severity,
                "attack_type": "control_injection" if event.get("action") == "BLOCK" else None,
            }
            self._append(self.security_events, item)
            self._persist_security_event(item)
            if event.get("action") == "BLOCK":
                self._append(self.alerts, item)
            return

        if event_type == "telemetry_finding" and event.get("detected"):
            self._append(self.alerts, event)
            self._append(self.security_events, event)
            self._persist_security_event(event)
            return

        if event_type == "response_action":
            self._append(self.response_history, event)
            self._persist_response(event)
            return

        if event_type == "recovery":
            item = {
                **event,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "vehicle_id": VEHICLE_ID,
            }
            self._append(self.recovery_history, item)
            with SessionLocal() as db:
                db.add(
                    RecoveryRecord(
                        vehicle_id=VEHICLE_ID,
                        status=str(item.get("status", "RECOVERED")),
                        restored_ecus=sorted(self.runtime.get_ecu_status().keys()),
                        details=item,
                    )
                )
                db.commit()

    def record_telemetry(self, topic: str, payload: dict[str, Any]) -> None:
        ecu = str(payload.get("ecu", "UNKNOWN")).upper()
        item = {
            "topic": topic,
            "vehicle_id": payload.get("vehicle_id"),
            "ecu": ecu,
            "message_id": payload.get("message_id"),
            "sequence": payload.get("sequence"),
            "timestamp": payload.get("timestamp", time.time()),
            "data": payload.get("data", {}),
        }
        with self._lock:
            self.current_telemetry[ecu] = item
        now = time.time()
        if now - self._last_db_telemetry_time.get(ecu, 0.0) >= self.telemetry_db_interval:
            self._persist_telemetry(item)
            self._last_db_telemetry_time[ecu] = now

    def record_attack(self, item: dict[str, Any]) -> None:
        self._append(self.attack_history, item)
        with SessionLocal() as db:
            db.add(
                AttackRecord(
                    name=item["name"],
                    target_ecu=item.get("ecu"),
                    topic=item.get("topic"),
                    status="published" if item.get("published") else "failed",
                    description=item.get("description"),
                    details=item,
                )
            )
            db.commit()

    def _persist_telemetry(self, item: dict[str, Any]) -> None:
        with SessionLocal() as db:
            db.add(
                TelemetryRecord(
                    vehicle_id=str(item.get("vehicle_id") or VEHICLE_ID),
                    ecu=str(item["ecu"]),
                    topic=str(item["topic"]),
                    message_id=item.get("message_id"),
                    sequence=item.get("sequence"),
                    source_timestamp=item.get("timestamp"),
                    data=dict(item.get("data") or {}),
                )
            )
            db.commit()

    def _persist_security_event(self, event: dict[str, Any]) -> None:
        with SessionLocal() as db:
            db.add(
                SecurityEventRecord(
                    event_type=str(event.get("event_type") or event.get("type") or "security"),
                    severity=str(event.get("severity", "INFO")),
                    ecu=event.get("ecu"),
                    attack_type=event.get("attack_type"),
                    action=event.get("action"),
                    reason=event.get("reason"),
                    details=dict(event),
                )
            )
            db.commit()

    def _persist_response(self, event: dict[str, Any]) -> None:
        with SessionLocal() as db:
            db.add(
                ResponseRecord(
                    action=str(event.get("action", "unknown")),
                    ecu=str(event.get("ecu", "UNKNOWN")),
                    attack_type=str(event.get("attack_type", "unknown")),
                    severity=str(event.get("severity", "INFO")),
                    executed=bool(event.get("executed")),
                    reason=str(event.get("reason", "")),
                )
            )
            db.commit()

    def snapshot(self) -> dict[str, Any]:
        state = self.runtime.get_state_snapshot()
        ground_truth = self.runtime.get_ground_truth()
        risk = self._risk_status()
        with self._lock:
            telemetry = dict(self.current_telemetry)
            alerts = list(self.alerts[-50:])
            events = list(self.security_events[-50:])
            attacks = list(self.attack_history[-50:])
            responses = list(self.response_history[-50:])
            recovery = list(self.recovery_history[-20:])
        return {
            "timestamp": time.time(),
            "runtime": self.runtime.get_runtime_status(),
            "vehicle": {
                "id": VEHICLE_ID,
                "status": "ONLINE" if self.runtime.running else "OFFLINE",
                **state,
                "ground_truth": ground_truth,
            },
            "ecus": self.runtime.get_ecu_status(),
            "telemetry": telemetry,
            "security": {"risk": risk, "alerts": alerts, "recent_events": events},
            "attacks": attacks,
            "responses": responses,
            "recovery": recovery,
        }

    def _risk_status(self) -> dict[str, Any]:
        with self._lock:
            critical = sum(1 for x in self.alerts if str(x.get("severity", "")).upper() == "CRITICAL")
            high = sum(1 for x in self.alerts if str(x.get("severity", "")).upper() == "HIGH")
        score = min(100, critical * 60 + high * 25)
        level = "CRITICAL" if critical else "HIGH" if high else "LOW"
        return {"score": score, "level": level, "critical": critical, "high": high}

    def clear_live_alerts_after_recovery(self) -> None:
        with self._lock:
            self.alerts.clear()

    def evaluation(self) -> dict[str, Any]:
        with SessionLocal() as db:
            attacks = db.scalar(select(func.count()).select_from(AttackRecord)) or 0
            telemetry = db.scalar(select(func.count()).select_from(TelemetryRecord)) or 0
            security = db.scalar(select(func.count()).select_from(SecurityEventRecord)) or 0
            responses = db.scalar(select(func.count()).select_from(ResponseRecord)) or 0
            executed_responses = db.scalar(
                select(func.count()).select_from(ResponseRecord).where(ResponseRecord.executed.is_(True))
            ) or 0
            recovered = db.scalar(select(func.count()).select_from(RecoveryRecord)) or 0

        return {
            "generated_at": time.time(),
            "attacks_launched": attacks,
            "telemetry_records": telemetry,
            "security_events": security,
            "responses_recorded": responses,
            "responses_executed": executed_responses,
            "recovery_events": recovered,
            "runtime_running": self.runtime.running,
            "false_positive_rate": None,
            "detection_time_ms": None,
            "response_time_ms": None,
            "recovery_time_ms": None,
            "note": "Timing and false-positive metrics require a labeled benchmark run; they are not inferred from raw history.",
        }


service = SecureEVService()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    service.hydrate_from_db()
    yield
    if service.runtime.running:
        service.runtime.stop()


app = FastAPI(title="SecureEV API", version="1.3.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "service": "secureev-api", "runtime_running": service.runtime.running, "timestamp": time.time()}


@app.get("/snapshot")
def snapshot() -> dict[str, Any]:
    return service.snapshot()


@app.get("/vehicle/state")
def vehicle_state() -> dict[str, Any]:
    return service.snapshot()["vehicle"]


@app.get("/vehicle/telemetry")
def vehicle_telemetry() -> dict[str, Any]:
    return service.current_telemetry


@app.get("/ecus")
def ecus() -> dict[str, Any]:
    return {"ecus": service.runtime.get_ecu_status()}


@app.get("/security/alerts")
def security_alerts(limit: int = Query(default=50, ge=1, le=200)) -> list[dict[str, Any]]:
    return service.alerts[-limit:]


@app.get("/security/status")
def security_status() -> dict[str, Any]:
    return {"risk": service._risk_status(), "runtime": service.runtime.get_runtime_status()}


@app.get("/attacks")
def attacks(limit: int = Query(default=50, ge=1, le=200)) -> list[dict[str, Any]]:
    return service.attack_history[-limit:]


@app.get("/responses")
def responses(limit: int = Query(default=50, ge=1, le=200)) -> list[dict[str, Any]]:
    return service.response_history[-limit:]


@app.get("/runtime/status")
def runtime_status() -> dict[str, Any]:
    return service.runtime.get_runtime_status()


@app.post("/runtime/start")
def runtime_start() -> dict[str, Any]:
    ok, message = service.runtime.start()
    if not ok:
        raise HTTPException(status_code=503, detail=message)
    return {"ok": True, "message": message}


@app.post("/runtime/stop")
def runtime_stop() -> dict[str, Any]:
    ok, message = service.runtime.stop()
    return {"ok": ok, "message": message}


@app.post("/runtime/recover")
def runtime_recover() -> dict[str, Any]:
    try:
        ok, message = service.runtime.recover()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if ok:
        service.clear_live_alerts_after_recovery()
    return {"ok": ok, "message": message}


@app.post("/vehicle/autonomous/start")
def autonomous_start(request: AutonomousRequest | None = None) -> dict[str, Any]:
    try:
        status = service.runtime.set_autonomous_mode(
            request.target_speed_kmh if request is not None else None,
            replan=True,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True, "mode": status}


@app.post("/vehicle/autonomous/stop")
def autonomous_stop() -> dict[str, Any]:
    try:
        status = service.runtime.set_manual_mode()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True, "mode": status}


@app.post("/vehicle/autonomous/replan")
def autonomous_replan() -> dict[str, Any]:
    try:
        status = service.runtime.set_autonomous_mode(replan=True)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True, "mode": status}


@app.post("/vehicle/control")
def vehicle_control(request: ControlRequest) -> dict[str, Any]:
    if not service.runtime.running:
        raise HTTPException(status_code=409, detail="SecureEV runtime is not running.")
    if request.throttle > 0 and request.brake > 0:
        raise HTTPException(status_code=422, detail="Throttle and brake cannot be applied together.")
    try:
        published = service.runtime.send_control(request.throttle, request.brake, request.steer)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": published, "control": request.model_dump()}


@app.post("/vehicle/emergency-brake")
def emergency_brake() -> dict[str, Any]:
    if not service.runtime.running:
        raise HTTPException(status_code=409, detail="SecureEV runtime is not running.")
    try:
        published = service.runtime.emergency_brake()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": published}


@app.post("/attacks/launch")
def launch_attack(request: AttackRequest) -> dict[str, Any]:
    try:
        result = service.runtime.launch_attack(request.name)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    service.record_attack(result)
    return result


@app.post("/camera/start")
def camera_start() -> dict[str, Any]:
    try:
        ok, message = service.runtime.enable_camera()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": ok, "message": message}


@app.post("/camera/stop")
def camera_stop() -> dict[str, Any]:
    ok, message = service.runtime.disable_camera()
    return {"ok": ok, "message": message}


@app.get("/camera/frame.jpg")
def camera_frame() -> Response:
    if not service.runtime.running:
        raise HTTPException(status_code=409, detail="SecureEV runtime is not running.")
    frame = service.runtime.get_camera_jpeg()
    if not frame:
        raise HTTPException(status_code=503, detail="Camera frame is not available yet.")
    return Response(content=frame, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/camera/mjpeg")
def camera_mjpeg() -> StreamingResponse:
    if not service.runtime.running:
        raise HTTPException(status_code=409, detail="SecureEV runtime is not running.")
    return StreamingResponse(
        service.runtime.camera_mjpeg_stream(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
    )


@app.get("/reports/summary")
def report_summary() -> dict[str, Any]:
    with SessionLocal() as db:
        counts = {
            "telemetry_records": db.scalar(select(func.count()).select_from(TelemetryRecord)) or 0,
            "security_events": db.scalar(select(func.count()).select_from(SecurityEventRecord)) or 0,
            "attacks": db.scalar(select(func.count()).select_from(AttackRecord)) or 0,
            "responses": db.scalar(select(func.count()).select_from(ResponseRecord)) or 0,
            "recovery_events": db.scalar(select(func.count()).select_from(RecoveryRecord)) or 0,
        }
    return {"generated_at": time.time(), "runtime": service.runtime.get_runtime_status(), "risk": service._risk_status(), "database": counts}


@app.get("/reports/evaluation")
def report_evaluation() -> dict[str, Any]:
    return service.evaluation()


@app.get("/reports/export.json")
def report_export() -> JSONResponse:
    payload = {
        "report": service.evaluation(),
        "summary": {"runtime": service.runtime.get_runtime_status(), "risk": service._risk_status()},
        "attacks": service.attack_history[-200:],
        "responses": service.response_history[-200:],
        "security_events": service.security_events[-200:],
        "recovery": service.recovery_history[-100:],
    }
    return JSONResponse(payload, headers={"Content-Disposition": 'attachment; filename="secureev_report.json"'})


@app.get("/reports/export.csv")
def report_export_csv() -> Response:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["time", "type", "event", "ecu", "severity", "status", "reason"])
    for attack in service.attack_history[-200:]:
        writer.writerow([attack.get("timestamp") or attack.get("recorded_at"), "ATTACK", attack.get("name"), attack.get("target_ecu") or attack.get("ecu"), "", attack.get("status"), attack.get("description", "")])
    for response in service.response_history[-200:]:
        writer.writerow([response.get("timestamp") or response.get("recorded_at"), "RESPONSE", response.get("action"), response.get("ecu"), response.get("severity"), "EXECUTED" if response.get("executed") else "FAILED", response.get("reason", "")])
    for event in service.security_events[-200:]:
        writer.writerow([event.get("timestamp") or event.get("recorded_at"), "SECURITY", event.get("attack_type") or event.get("event_type"), event.get("ecu"), event.get("severity"), event.get("action") or ("DETECTED" if event.get("detected") else "RECORDED"), event.get("reason", "")])
    return Response(content=buffer.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="secureev_report.csv"'})


@app.get("/history/telemetry")
def history_telemetry(
    ecu: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict[str, Any]]:
    with SessionLocal() as db:
        query = select(TelemetryRecord).order_by(TelemetryRecord.id.desc()).limit(limit)
        if ecu:
            query = query.where(TelemetryRecord.ecu == ecu.strip().upper())
        rows = list(db.scalars(query))
    return [
        {
            "id": row.id,
            "recorded_at": row.recorded_at.isoformat() if row.recorded_at else None,
            "vehicle_id": row.vehicle_id,
            "ecu": row.ecu,
            "topic": row.topic,
            "message_id": row.message_id,
            "sequence": row.sequence,
            "source_timestamp": row.source_timestamp,
            "data": row.data,
        }
        for row in reversed(rows)
    ]


@app.get("/history/security")
def history_security(limit: int = Query(default=100, ge=1, le=500)) -> list[dict[str, Any]]:
    with SessionLocal() as db:
        rows = list(db.scalars(select(SecurityEventRecord).order_by(SecurityEventRecord.id.desc()).limit(limit)))
    return [service._security_row(row) for row in reversed(rows)]


@app.get("/history/attacks")
def history_attacks(limit: int = Query(default=100, ge=1, le=500)) -> list[dict[str, Any]]:
    with SessionLocal() as db:
        rows = list(db.scalars(select(AttackRecord).order_by(AttackRecord.id.desc()).limit(limit)))
    return [
        {
            "id": row.id,
            "recorded_at": row.recorded_at.isoformat() if row.recorded_at else None,
            "name": row.name,
            "target_ecu": row.target_ecu,
            "topic": row.topic,
            "status": row.status,
            "description": row.description,
            "details": row.details,
            **((row.details or {}).copy() if isinstance(row.details, dict) else {}),
        }
        for row in reversed(rows)
    ]


@app.get("/history/responses")
def history_responses(limit: int = Query(default=100, ge=1, le=500)) -> list[dict[str, Any]]:
    with SessionLocal() as db:
        rows = list(db.scalars(select(ResponseRecord).order_by(ResponseRecord.id.desc()).limit(limit)))
    return [
        {
            "id": row.id,
            "recorded_at": row.recorded_at.isoformat() if row.recorded_at else None,
            "action": row.action,
            "ecu": row.ecu,
            "attack_type": row.attack_type,
            "severity": row.severity,
            "executed": row.executed,
            "reason": row.reason,
        }
        for row in reversed(rows)
    ]


@app.get("/history/recovery")
def history_recovery(limit: int = Query(default=100, ge=1, le=500)) -> list[dict[str, Any]]:
    with SessionLocal() as db:
        rows = list(db.scalars(select(RecoveryRecord).order_by(RecoveryRecord.id.desc()).limit(limit)))
    return [
        {
            "id": row.id,
            "recorded_at": row.recorded_at.isoformat() if row.recorded_at else None,
            "vehicle_id": row.vehicle_id,
            "status": row.status,
            "restored_ecus": row.restored_ecus,
            "details": row.details,
        }
        for row in reversed(rows)
    ]


@app.websocket("/ws/live")
async def websocket_live(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(service.snapshot())
            await asyncio.sleep(0.20)
    except (WebSocketDisconnect, RuntimeError):
        return
