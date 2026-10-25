"""Live SecureEV runtime adapter used by the FastAPI application.

The runtime connects the existing CARLA, Digital Twin, MQTT, Red Team and Blue
Team modules to the Person 2 application layer.  CARLA access remains isolated
behind ``simulation.carla_bridge.CarlaBridge``.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from typing import Any, Callable, Iterator

from blue_team.ground_truth_validator import GroundTruthValidator
from blue_team.integrity_checker import IntegrityChecker
from blue_team.response_engine import ResponseEngine
from blue_team.runtime_response import RuntimeResponseCoordinator
from blue_team.security_gateway import SecurityGateway
from digital_twin.acu import ACU
from digital_twin.bcm import BCM
from digital_twin.bms import BMS
from digital_twin.camera_module import CameraModule
from digital_twin.charging_controller import ChargingController
from digital_twin.digital_twin_manager import DigitalTwinManager
from digital_twin.mcu import MCU
from digital_twin.ota_manager import OTAManager
from digital_twin.tcu import TCU
from digital_twin.vcu import VCU
from digital_twin.vehicle_state import VehicleState
from network.control_bridge import MQTTControlBridge
from network.control_schema import create_vcu_control_message
from network.ecu_telemetry_bridge import ECUTelemetryBridge
from network.mqtt_config import (
    ACU_TELEMETRY,
    BMS_TELEMETRY,
    BCM_TELEMETRY,
    CAMERA_TELEMETRY,
    CHARGING_TELEMETRY,
    MCU_TELEMETRY,
    OTA_TELEMETRY,
    TCU_TELEMETRY,
    VCU_TELEMETRY,
    VEHICLE_ID,
)
from network.publisher import MQTTPublisher
from network.subscriber import MQTTSubscriber
from red_team.control_injection import ControlInjectionAttacker
from red_team.data_spoofing import DataSpoofingAttacker
from red_team.firmware_attacks import FirmwareAttacker
from simulation.carla_bridge import CarlaBridge

ECU_TOPICS = {
    "VCU": VCU_TELEMETRY,
    "BMS": BMS_TELEMETRY,
    "BCM": BCM_TELEMETRY,
    "MCU": MCU_TELEMETRY,
    "TCU": TCU_TELEMETRY,
    "ACU": ACU_TELEMETRY,
    "CHG": CHARGING_TELEMETRY,
    "CAM": CAMERA_TELEMETRY,
    "OTA": OTA_TELEMETRY,
}

VALIDATED_TELEMETRY_ECUS = {"VCU", "BMS", "TCU"}

CAMERA_ENABLED_BY_DEFAULT = os.getenv("SECUREEV_ENABLE_CAMERA", "0").strip().lower() in {"1", "true", "yes", "on"}
AUTONOMOUS_BY_DEFAULT = os.getenv("SECUREEV_AUTONOMOUS_DEFAULT", "1").strip().lower() in {"1", "true", "yes", "on"}
AUTONOMOUS_TARGET_SPEED_KMH = float(os.getenv("SECUREEV_AUTONOMOUS_SPEED_KMH", "28"))


class SecureEVRuntime:
    """Own one live SecureEV CARLA/digital-twin session."""

    def __init__(
        self,
        event_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.event_callback = event_callback
        self._lock = threading.RLock()
        self._attack_condition = threading.Condition()
        self._telemetry_outcomes: dict[str, dict[str, Any]] = {}
        self._control_outcomes: dict[str, dict[str, Any]] = {}
        self._stop_event = threading.Event()
        self._quarantine_reported: set[str] = set()
        self._thread: threading.Thread | None = None

        self.running = False
        self.start_error: str | None = None
        self.started_at: float | None = None
        self.last_loop_time: float | None = None

        self.bridge: CarlaBridge | None = None
        self.state: VehicleState | None = None
        self.manager: DigitalTwinManager | None = None
        self.vcu: VCU | None = None
        self.bms: BMS | None = None
        self.bcm: BCM | None = None
        self.mcu: MCU | None = None
        self.tcu: TCU | None = None
        self.acu: ACU | None = None
        self.charging: ChargingController | None = None
        self.camera: CameraModule | None = None
        self.ota: OTAManager | None = None
        self.camera_enabled = CAMERA_ENABLED_BY_DEFAULT
        self.autonomous_by_default = AUTONOMOUS_BY_DEFAULT
        self.autonomous_target_speed_kmh = max(5.0, min(60.0, AUTONOMOUS_TARGET_SPEED_KMH))

        self.publisher: MQTTPublisher | None = None
        self.telemetry_bridge: ECUTelemetryBridge | None = None
        self.control_subscriber: MQTTSubscriber | None = None
        self.control_bridge: MQTTControlBridge | None = None
        self.telemetry_subscriber: MQTTSubscriber | None = None
        self.control_sequence = 0

        self.security_gateway: SecurityGateway | None = None
        self.response_engine: ResponseEngine | None = None
        self.runtime_response: RuntimeResponseCoordinator | None = None
        self.ground_truth_validator = GroundTruthValidator()
        firmware_key = os.getenv("SECUREEV_FIRMWARE_SIGNING_KEY")
        self.integrity_checker = IntegrityChecker(
            firmware_key.encode("utf-8") if firmware_key else None
        )

        self.control_attacker: ControlInjectionAttacker | None = None
        self.data_attacker: DataSpoofingAttacker | None = None
        self.firmware_attacker = FirmwareAttacker()

    def start(self) -> tuple[bool, str]:
        with self._lock:
            if self.running:
                return True, "SecureEV runtime is already running."
            self.start_error = None
            self.camera_enabled = CAMERA_ENABLED_BY_DEFAULT
            self._stop_event.clear()
            self._quarantine_reported.clear()

        with self._attack_condition:
            self._telemetry_outcomes.clear()
            self._control_outcomes.clear()

        bridge: CarlaBridge | None = None
        publisher: MQTTPublisher | None = None
        control_subscriber: MQTTSubscriber | None = None
        telemetry_subscriber: MQTTSubscriber | None = None

        try:
            bridge = CarlaBridge(host="localhost", port=2000, timeout=10.0)
            bridge.spawn_vehicle("vehicle.tesla.model3", spawn_index=0)
            bridge.set_autopilot(False)
            # CARLA RGB sensors can materially increase GPU pressure on some
            # Windows systems. Keep the core SecureEV runtime stable by making
            # the camera opt-in; it can be enabled from the dashboard.
            if self.camera_enabled:
                bridge.attach_rgb_camera(width=320, height=180, fov=90.0)

            state = VehicleState(battery_soc=80.0)
            vcu = VCU(state, bridge)
            charging = ChargingController(state, charging_power_kw=11.0)
            bms = BMS(state, vcu=vcu, charging_controller=charging)
            bcm = BCM(state)
            mcu = MCU(state, vcu=vcu)
            tcu = TCU(state, bridge)
            acu = ACU(state)
            camera = CameraModule(state, bridge)
            ota = OTAManager(state, self.integrity_checker)

            # Keep the established 10 Hz Digital Twin timing.  The spectator
            # is smoothed independently, so increasing the ECU rate is not
            # required just to make the visual follow camera stable.
            manager = DigitalTwinManager(vehicle_state=state, tick_rate_hz=10.0)
            for ecu in (vcu, bms, bcm, mcu, tcu, acu, charging, camera, ota):
                manager.register_ecu(ecu)

            # Default to an autonomous urban patrol. This gives the demo a
            # moving, road-following EV without requiring manual input.
            if self.autonomous_by_default:
                acu.enable_autonomous_mode(self.autonomous_target_speed_kmh)
                bridge.start_autonomous_patrol(self.autonomous_target_speed_kmh)

            publisher = MQTTPublisher(client_id=f"secureev-backend-{uuid.uuid4().hex[:8]}")
            if not publisher.connect():
                raise RuntimeError(
                    "MQTT broker is unavailable at localhost:1883. "
                    "Start Mosquitto before starting the live runtime."
                )

            telemetry_bridge = ECUTelemetryBridge(publisher=publisher, vehicle_id=VEHICLE_ID)
            security_gateway = SecurityGateway(
                expected_vehicle_id=VEHICLE_ID,
                alert_handler=self._on_security_event,
            )
            response_engine = ResponseEngine(vcu=vcu)
            runtime_response = RuntimeResponseCoordinator(response_engine)

            control_subscriber = MQTTSubscriber(
                client_id=f"secureev-backend-control-{uuid.uuid4().hex[:8]}",
                verbose=False,
            )
            control_bridge = MQTTControlBridge(
                vcu=vcu,
                subscriber=control_subscriber,
                vehicle_id=VEHICLE_ID,
                security_gateway=security_gateway,
            )
            if not control_bridge.start():
                raise RuntimeError("Failed to start the protected MQTT control bridge.")

            telemetry_subscriber = MQTTSubscriber(
                client_id=f"secureev-backend-telemetry-{uuid.uuid4().hex[:8]}",
                message_handler=self._on_telemetry_message,
                verbose=False,
            )
            if not telemetry_subscriber.connect():
                raise RuntimeError("Failed to start the MQTT telemetry observer.")

            for topic in ECU_TOPICS.values():
                if not telemetry_subscriber.subscribe(topic, qos=1):
                    raise RuntimeError(f"Failed to subscribe to telemetry topic: {topic}")

            self._bind_runtime(
                bridge=bridge,
                state=state,
                manager=manager,
                vcu=vcu,
                bms=bms,
                bcm=bcm,
                mcu=mcu,
                tcu=tcu,
                acu=acu,
                charging=charging,
                camera=camera,
                ota=ota,
                publisher=publisher,
                telemetry_bridge=telemetry_bridge,
                control_subscriber=control_subscriber,
                control_bridge=control_bridge,
                telemetry_subscriber=telemetry_subscriber,
                security_gateway=security_gateway,
                response_engine=response_engine,
                runtime_response=runtime_response,
            )
            self.control_attacker = ControlInjectionAttacker(publisher=publisher)
            self.data_attacker = DataSpoofingAttacker(publisher=publisher)

            self._thread = threading.Thread(
                target=self._run_loop,
                name="secureev-runtime",
                daemon=True,
            )
            with self._lock:
                self.running = True
                self.started_at = time.time()
                self.last_loop_time = None
                self._thread.start()

            self._emit({"type": "runtime", "event": "started", "timestamp": time.time()})
            return True, "SecureEV runtime started."
        except Exception as exc:
            for subscriber in (telemetry_subscriber, control_subscriber):
                if subscriber is not None:
                    try:
                        subscriber.disconnect()
                    except Exception:
                        pass
            if publisher is not None:
                try:
                    publisher.disconnect()
                except Exception:
                    pass
            if bridge is not None:
                try:
                    bridge.cleanup()
                except Exception:
                    pass
            with self._lock:
                self.running = False
                self.start_error = str(exc)
            return False, str(exc)

    def stop(self) -> tuple[bool, str]:
        with self._lock:
            if not self.running:
                return True, "SecureEV runtime is already stopped."
            self.running = False
            self._stop_event.set()

        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=3.0)

        for subscriber in (self.telemetry_subscriber, self.control_subscriber):
            if subscriber is not None:
                try:
                    subscriber.disconnect()
                except Exception:
                    pass
        if self.publisher is not None:
            try:
                self.publisher.disconnect()
            except Exception:
                pass
        if self.bridge is not None:
            try:
                self.bridge.cleanup()
            except Exception:
                pass

        self._thread = None
        self._emit({"type": "runtime", "event": "stopped", "timestamp": time.time()})
        return True, "SecureEV runtime stopped."

    def recover(self, spawn_index: int = 0) -> tuple[bool, str]:
        """Return the simulated vehicle/security state to a safe baseline."""
        if not self.running:
            raise RuntimeError("Start the SecureEV runtime before recovery.")
        if self.bridge is None or self.bridge.vehicle is None:
            raise RuntimeError("No active CARLA vehicle is available for recovery.")

        self.bridge.reset_vehicle(spawn_index=spawn_index)
        if self.autonomous_by_default and self.acu is not None:
            self.acu.enable_autonomous_mode(self.autonomous_target_speed_kmh)
            self.bridge.start_autonomous_patrol(self.autonomous_target_speed_kmh)
        elif self.acu is not None:
            self.acu.disable_autonomous_mode()
        if self.camera is not None:
            try:
                self.camera.set_live_source()
            except Exception:
                pass
        if self.response_engine is not None:
            self.response_engine.clear_runtime_state()
        self._quarantine_reported.clear()
        if self.runtime_response is not None:
            self.runtime_response.handled_findings = 0
            self.runtime_response.detected_findings = 0

        self._emit(
            {
                "type": "recovery",
                "event": "completed",
                "status": "RECOVERED",
                "vehicle_id": VEHICLE_ID,
                "timestamp": time.time(),
            }
        )
        return True, "SecureEV recovered to the safe baseline."

    def _bind_runtime(self, **objects: Any) -> None:
        for name, value in objects.items():
            setattr(self, name, value)

    def _run_loop(self) -> None:
        assert self.manager is not None
        assert self.telemetry_bridge is not None
        assert self.control_bridge is not None

        # Keep ECU simulation/telemetry at the established 10 Hz, while
        # running control processing and spectator updates at 30 Hz.  This
        # prevents the spectator from visibly jumping between 10 Hz frames.
        twin_interval = 1.0 / self.manager.tick_rate_hz
        loop_interval = 1.0 / 30.0
        next_twin_tick = time.monotonic()

        while not self._stop_event.is_set():
            started = time.monotonic()
            try:
                now = time.monotonic()

                # Process newly-arrived commands on every high-rate loop so
                # dashboard controls remain responsive.
                self.control_bridge.process_pending_commands(max_commands=20)

                # Digital-twin ECU updates and MQTT telemetry remain at 10 Hz.
                if now >= next_twin_tick:
                    telemetry = self.manager.tick()
                    next_twin_tick += twin_interval
                    if next_twin_tick <= now:
                        next_twin_tick = now + twin_interval

                    for ecu_id, data in telemetry.items():
                        topic = ECU_TOPICS.get(ecu_id)
                        if topic is None:
                            continue
                        try:
                            self.telemetry_bridge.publish_telemetry(
                                ecu_id=ecu_id,
                                topic=topic,
                                telemetry=data,
                            )
                        except Exception as exc:
                            self._emit(
                                {
                                    "type": "runtime_error",
                                    "stage": "telemetry_publish",
                                    "ecu": ecu_id,
                                    "error": str(exc),
                                    "timestamp": time.time(),
                                }
                            )

                # The spectator camera is updated much more frequently than
                # the ECU loop, and CarlaBridge applies frame-rate-independent
                # damping to make the third-person view smooth.
                if self.bridge is not None and self.bridge.vehicle is not None:
                    self.bridge.follow_vehicle(
                        distance=10.0,
                        height=4.5,
                        pitch=-16.0,
                        smoothing=12.0,
                    )

                self.last_loop_time = time.time()
            except Exception as exc:
                self._emit(
                    {
                        "type": "runtime_error",
                        "stage": "simulation_loop",
                        "error": str(exc),
                        "timestamp": time.time(),
                    }
                )

            elapsed = time.monotonic() - started
            self._stop_event.wait(max(0.0, loop_interval - elapsed))

    def _emit(self, event: dict[str, Any]) -> None:
        if self.event_callback is None:
            return
        try:
            self.event_callback(event)
        except Exception:
            pass

    def _on_telemetry_message(self, topic: str, payload: dict[str, Any]) -> None:
        ecu = str(payload.get("ecu", "")).upper()
        if self.response_engine is not None and not self.response_engine.is_ecu_trusted(ecu):
            if ecu not in self._quarantine_reported:
                self._quarantine_reported.add(ecu)
                self._emit(
                    {
                        "type": "telemetry_quarantined",
                        "ecu": ecu,
                        "topic": topic,
                        "message_id": payload.get("message_id"),
                        "reason": "ECU is isolated after a confirmed integrity finding",
                        "timestamp": time.time(),
                    }
                )
            return

        if ecu not in VALIDATED_TELEMETRY_ECUS:
            self._emit({"type": "telemetry", "topic": topic, "payload": payload, "timestamp": time.time()})
            return

        try:
            ground_truth = self.get_ground_truth()
            trusted_soc = self.state.battery_soc if self.state is not None else None
            if ecu in {"VCU", "TCU"} and ground_truth is None:
                return

            finding = self.ground_truth_validator.validate_message(
                topic,
                payload,
                carla_ground_truth=ground_truth,
                trusted_battery_soc=trusted_soc,
            )
            message_id = payload.get("message_id")
            if isinstance(message_id, str):
                with self._attack_condition:
                    self._telemetry_outcomes[message_id] = {
                        "detected": finding.detected,
                        "attack_type": finding.attack_type,
                        "reason": finding.reason,
                    }
                    if len(self._telemetry_outcomes) > 500:
                        self._telemetry_outcomes.pop(next(iter(self._telemetry_outcomes)))
                    self._attack_condition.notify_all()
            trusted = not finding.detected
            self._emit(
                {
                    "type": "telemetry_finding",
                    "event_type": "ground_truth_validation",
                    "timestamp": time.time(),
                    "detected": bool(finding.detected),
                    "attack_type": finding.attack_type,
                    "ecu": finding.ecu,
                    "field": finding.field,
                    "severity": finding.severity,
                    "reason": finding.reason,
                    "deviation": finding.deviation,
                    "tolerance": finding.tolerance,
                    "actual_value": finding.actual_value,
                    "reported_value": finding.reported_value,
                }
            )

            if finding.detected and self.runtime_response is not None:
                result = self.runtime_response.handle_finding(finding)
                actions = list(result.actions)

                # While the EV is driving autonomously, any confirmed high or
                # critical integrity anomaly causes a fail-safe stop. Critical
                # findings already include an emergency brake in the normal
                # response policy; HIGH findings get the autonomous safety
                # override here.
                if (
                    finding.detected
                    and str(finding.severity).upper() in {"HIGH", "CRITICAL"}
                    and self.state is not None
                    and self.state.autonomous_mode
                    and not any(action.action == "emergency_brake" for action in actions)
                    and self.response_engine is not None
                ):
                    actions.append(
                        self.response_engine.emergency_brake(
                            ecu=finding.ecu,
                            attack_type=finding.attack_type,
                            severity=finding.severity,
                            reason="autonomous safety stop after confirmed telemetry integrity anomaly",
                        )
                    )

                for action in actions:
                    if action.action == "emergency_brake":
                        self._enter_safe_stop()
                    self._emit(
                        {
                            "type": "response_action",
                            "event_type": "response",
                            "timestamp": action.timestamp,
                            "action": action.action,
                            "ecu": action.ecu,
                            "attack_type": action.attack_type,
                            "severity": action.severity,
                            "executed": action.executed,
                            "reason": action.reason,
                        }
                    )
            if trusted:
                self._emit({"type": "telemetry", "topic": topic, "payload": payload, "timestamp": time.time()})
        except Exception as exc:
            self._emit(
                {
                    "type": "runtime_error",
                    "stage": "telemetry_validation",
                    "error": str(exc),
                    "timestamp": time.time(),
                }
            )

    def _on_security_event(self, event: Any) -> None:
        message_id = getattr(event, "message_id", None)
        if isinstance(message_id, str):
            with self._attack_condition:
                self._control_outcomes[message_id] = {
                    "action": event.action,
                    "reason": event.reason,
                }
                if len(self._control_outcomes) > 500:
                    self._control_outcomes.pop(next(iter(self._control_outcomes)))
                self._attack_condition.notify_all()

        self._emit(
            {
                "type": "security_gateway",
                "action": event.action,
                "reason": event.reason,
                "topic": event.topic,
                "ecu": event.ecu,
                "command": event.command,
                "message_id": event.message_id,
                "sequence": event.sequence,
                "timestamp": event.checked_at,
            }
        )

        # A blocked malicious VCU command is itself a security event. During
        # autonomous patrol, fail closed and stop the EV so the attack has a
        # visible, physical consequence in the simulator.
        if getattr(event, "action", None) == "BLOCK" and self.response_engine is not None:
            action = self.response_engine.emergency_brake(
                ecu=str(getattr(event, "ecu", None) or "VCU"),
                attack_type="control_injection",
                severity="HIGH",
                reason=str(getattr(event, "reason", "blocked malicious control command")),
            )
            self._enter_safe_stop()
            self._emit(
                {
                    "type": "response_action",
                    "event_type": "response",
                    "timestamp": action.timestamp,
                    "action": action.action,
                    "ecu": action.ecu,
                    "attack_type": action.attack_type,
                    "severity": action.severity,
                    "executed": action.executed,
                    "reason": action.reason,
                }
            )

    def get_ground_truth(self) -> dict[str, Any] | None:
        if self.bridge is None or self.bridge.vehicle is None:
            return None
        try:
            return self.bridge.get_ground_truth_state()
        except Exception:
            return None

    def get_state_snapshot(self) -> dict[str, Any]:
        state = self.state
        if state is None:
            return {}
        return {
            "speed_kmh": state.speed_kmh,
            "acceleration_mps2": state.acceleration,
            "battery_soc": state.battery_soc,
            "battery_temp": state.battery_temp,
            "motor_rpm": state.motor_rpm,
            "motor_temp": state.motor_temp,
            "doors_locked": state.doors_locked,
            "doors_open": state.doors_open,
            "reported_gps": state.reported_gps,
            "autonomous_mode": state.autonomous_mode,
            "planned_throttle": state.planned_throttle,
            "planned_brake": state.planned_brake,
            "planned_steer": state.planned_steer,
            "charging_state": state.charging_state,
            "charge_port_locked": state.charge_port_locked,
            "vehicle_disabled_flag": state.vehicle_disabled_flag,
            "camera_feed_source": state.camera_feed_source,
            "firmware_version": state.firmware_version,
            "last_updated": state.last_updated,
        }

    def get_ecu_status(self) -> dict[str, str]:
        manager = self.manager
        if manager is None:
            return {}
        return {ecu_id: ecu.status for ecu_id, ecu in manager.ecus.items()}

    def get_runtime_status(self) -> dict[str, Any]:
        control = self.control_bridge
        response = self.runtime_response
        return {
            "running": self.running,
            "started_at": self.started_at,
            "last_loop_time": self.last_loop_time,
            "start_error": self.start_error,
            "vehicle_id": VEHICLE_ID,
            "ecu_status": self.get_ecu_status(),
            "control_bridge": {
                "received": control.received_count if control else 0,
                "accepted": control.accepted_count if control else 0,
                "rejected": control.rejected_count if control else 0,
                "last_command": control.last_command if control else None,
                "last_rejection_reason": control.last_rejection_reason if control else None,
            },
            "response": response.status() if response else {},
            "integrity": {
                "firmware_signature_configured": self.integrity_checker.firmware_verification_configured,
                "untrusted_ecus": response.response_engine.get_status()["untrusted_ecus"]
                if response is not None
                else [],
            },
            "camera": self.camera_status(),
            "autonomy": self.bridge.get_autonomy_status() if self.bridge is not None else {"enabled": False, "mode": "MANUAL"},
        }

    def camera_status(self) -> dict[str, Any]:
        camera = self.camera
        if camera is None:
            return {"enabled": self.camera_enabled, "attached": False, "frame_available": False}
        return {
            "enabled": self.camera_enabled,
            "attached": self.bridge is not None and self.bridge.camera is not None,
            "frame_available": bool(camera.frame_available),
            "frame_sequence": int(camera.frame_sequence),
            "source": camera.vehicle_state.camera_feed_source,
            "last_frame_timestamp": camera.last_frame_timestamp,
            "last_frame_size": camera.last_frame_size,
        }

    def get_camera_jpeg(self) -> bytes | None:
        if self.camera is None or not self.running:
            return None
        return self.bridge.get_camera_jpeg() if self.bridge is not None else None

    def camera_mjpeg_stream(self, interval: float = 0.10) -> Iterator[bytes]:
        """Yield an MJPEG stream for a browser ``<img>`` element."""
        last_frame: bytes | None = None
        while self.running and not self._stop_event.is_set():
            frame = self.get_camera_jpeg()
            if frame and frame != last_frame:
                last_frame = frame
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Cache-Control: no-cache\r\n"
                    b"\r\n" + frame + b"\r\n"
                )
            time.sleep(interval)

    def enable_camera(self) -> tuple[bool, str]:
        """Attach the low-resolution CARLA RGB camera on demand."""
        if not self.running:
            raise RuntimeError("Start the SecureEV runtime before enabling the camera.")
        if self.bridge is None or self.bridge.vehicle is None:
            raise RuntimeError("No active CARLA vehicle is available.")
        if self.bridge.camera is not None:
            self.camera_enabled = True
            return True, "CARLA camera is already enabled."
        self.bridge.attach_rgb_camera(width=320, height=180, fov=90.0)
        self.camera_enabled = True
        return True, "CARLA camera enabled."

    def disable_camera(self) -> tuple[bool, str]:
        """Detach the RGB camera to reduce rendering/GPU load."""
        if self.bridge is not None:
            self.bridge.disable_rgb_camera()
        self.camera_enabled = False
        return True, "CARLA camera disabled."

    def set_autonomous_mode(
        self,
        target_speed_kmh: float | None = None,
        *,
        replan: bool = True,
    ) -> dict[str, Any]:
        if not self.running or self.bridge is None or self.bridge.vehicle is None or self.acu is None:
            raise RuntimeError("Start the SecureEV runtime before enabling autonomous mode.")
        speed = self.autonomous_target_speed_kmh if target_speed_kmh is None else max(5.0, min(60.0, float(target_speed_kmh)))
        self.autonomous_target_speed_kmh = speed
        self.acu.enable_autonomous_mode(speed)
        if replan or not self.bridge.autopilot_enabled:
            return self.bridge.start_autonomous_patrol(speed)
        return self.bridge.get_autonomy_status()

    def set_manual_mode(self) -> dict[str, Any]:
        if not self.running or self.bridge is None or self.acu is None:
            raise RuntimeError("Start the SecureEV runtime before enabling manual mode.")
        self.bridge.stop_autonomous_patrol()
        self.acu.disable_autonomous_mode()
        return self.bridge.get_autonomy_status()

    def send_control(self, throttle: float, brake: float, steer: float) -> bool:
        if self.publisher is None:
            raise RuntimeError("Runtime publisher is not available.")
        # Any user-authored VCU command explicitly switches the session to
        # manual mode so the Traffic Manager cannot fight the requested input.
        if self.acu is not None and self.acu.vehicle_state.autonomous_mode:
            self.set_manual_mode()
        self.control_sequence += 1
        message = create_vcu_control_message(
            command="set_control",
            data={"throttle": throttle, "brake": brake, "steer": steer},
            sequence=self.control_sequence,
            vehicle_id=VEHICLE_ID,
        )
        return self.publisher.publish("secureev/vcu/control", message, qos=1)

    def emergency_brake(self) -> bool:
        if self.publisher is None:
            raise RuntimeError("Runtime publisher is not available.")
        self._enter_safe_stop()
        self.control_sequence += 1
        message = create_vcu_control_message(
            command="emergency_brake",
            data={},
            sequence=self.control_sequence,
            vehicle_id=VEHICLE_ID,
        )
        return self.publisher.publish("secureev/vcu/control", message, qos=1)

    def _enter_safe_stop(self) -> None:
        """Disable autonomy and physically stop the simulated EV."""
        if self.bridge is not None and self.bridge.vehicle is not None:
            try:
                self.bridge.emergency_stop()
            except Exception as exc:
                self._emit({"type": "runtime_error", "stage": "safe_stop", "error": str(exc), "timestamp": time.time()})
        if self.acu is not None:
            try:
                self.acu.disable_autonomous_mode()
            except Exception:
                pass

    def launch_attack(self, name: str) -> dict[str, Any]:
        if not self.running or self.publisher is None:
            raise RuntimeError("Start the SecureEV runtime before launching attacks.")

        name = name.strip().lower()
        sequence = self.control_sequence + 1000

        if name == "gps_spoofing":
            assert self.data_attacker is not None
            scenario = self.data_attacker.gps_spoofing(sequence=1)
        elif name == "speed_spoofing":
            assert self.data_attacker is not None
            scenario = self.data_attacker.speed_spoofing(sequence=1)
        elif name == "battery_soc_spoofing":
            assert self.data_attacker is not None
            scenario = self.data_attacker.battery_soc_spoofing(sequence=1)
        elif name == "unauthorized_acceleration":
            assert self.control_attacker is not None
            scenario = self.control_attacker.unauthorized_acceleration(sequence=sequence)
        elif name == "out_of_range_control":
            assert self.control_attacker is not None
            scenario = self.control_attacker.out_of_range_control(sequence=sequence + 1)
        elif name == "unauthorized_command":
            assert self.control_attacker is not None
            scenario = self.control_attacker.unauthorized_command(sequence=sequence + 2)
        elif name == "replay_control":
            self.control_sequence += 1
            message = create_vcu_control_message(
                command="set_control",
                data={"throttle": 0.0, "brake": 0.0, "steer": 0.0},
                sequence=self.control_sequence,
                vehicle_id=VEHICLE_ID,
            )
            self.publisher.publish("secureev/vcu/control", message, qos=1)
            scenario = self.control_attacker.replay_control(message)
        elif name in {"cloud_update_attack", "ecu_update_attack"}:
            if self.ota is None:
                raise RuntimeError("OTA Manager is not available.")
            if name == "cloud_update_attack":
                trusted_package = b"SecureEV signed firmware package"
                trusted_signature = (
                    self.integrity_checker.sign_firmware_package(trusted_package)
                    if self.integrity_checker.firmware_verification_configured
                    else ""
                )
                scenario = self.firmware_attacker.cloud_update_attack(
                    "1.0.1", trusted_package, trusted_signature
                ) if trusted_signature else None
            else:
                scenario = self.firmware_attacker.ecu_update_attack(
                    "1.0.1", b"SecureEV local firmware package"
                )
            if scenario is None:
                event = {
                    "type": "integrity_finding",
                    "event_type": "firmware_integrity",
                    "attack_type": name,
                    "severity": "HIGH",
                    "detected": True,
                    "action": "update_rejected",
                    "reason": "Firmware signing key is not configured; update was rejected by default.",
                    "timestamp": time.time(),
                }
                self._emit(event)
                self.ota.reject_update(event["reason"])
                return {
                    "name": name,
                    "topic": "ota/firmware",
                    "ecu": "OTA",
                    "description": "Unsigned/tampered firmware update rejected.",
                    "published": True,
                    "detected": True,
                    "defended": True,
                    "defense_reason": event["reason"],
                    "timestamp": event["timestamp"],
                }

            self.ota.stage_update(scenario.version, scenario.package, scenario.signature)
            installed = self.ota.install_update()
            if installed:
                raise RuntimeError("Tampered firmware unexpectedly passed signature verification.")
            reason = self.ota.last_error or "Firmware signature verification failed; update rejected."
            self._emit(
                {
                    "type": "integrity_finding",
                    "event_type": "firmware_integrity",
                    "attack_type": name,
                    "severity": "HIGH",
                    "detected": True,
                    "action": "update_rejected",
                    "reason": reason,
                    "timestamp": time.time(),
                }
            )
            return {
                "name": name,
                "topic": "ota/firmware",
                "ecu": "OTA",
                "description": scenario.description,
                "published": True,
                "detected": True,
                "defended": True,
                "defense_reason": reason,
                "timestamp": time.time(),
            }
        else:
            raise ValueError(f"Unsupported attack: {name}")

        published = self.publisher.publish(scenario.topic, scenario.message, qos=1)
        outcome = self._await_attack_outcome(
            name,
            str(scenario.message.get("message_id", "")),
        ) if published else None
        return {
            "name": scenario.name,
            "topic": scenario.topic,
            "ecu": getattr(scenario, "ecu", "VCU"),
            "description": scenario.description,
            "published": bool(published),
            "detected": bool(outcome and outcome.get("detected")),
            "defended": bool(outcome and outcome.get("defended")),
            "outcome_status": "confirmed" if outcome and outcome.get("defended") else "unconfirmed",
            "defense_reason": outcome.get("reason") if outcome else None,
            "timestamp": time.time(),
        }

    def _await_attack_outcome(
        self,
        name: str,
        message_id: str,
        timeout: float = 2.0,
    ) -> dict[str, Any] | None:
        """Wait briefly for the subscriber-side decision on this exact packet."""
        deadline = time.monotonic() + timeout
        with self._attack_condition:
            while True:
                if name in {"gps_spoofing", "speed_spoofing", "battery_soc_spoofing"}:
                    outcome = self._telemetry_outcomes.get(message_id)
                    if outcome is not None and outcome.get("detected"):
                        return {"detected": True, "defended": True, "reason": outcome["reason"]}
                else:
                    outcome = self._control_outcomes.get(message_id)
                    if outcome is not None and outcome.get("action") == "BLOCK":
                        return {"detected": True, "defended": True, "reason": outcome["reason"]}

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._attack_condition.wait(remaining)
