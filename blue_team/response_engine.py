"""
response_engine.py

SecureEV Phase 8A - Attack-Resistant Response Engine.

The ResponseEngine consumes a confirmed security finding and selects a
proportionate mitigation action. It deliberately does not import CARLA.
CARLA remains isolated behind simulation/carla_bridge.py.

Policy used in Phase 8A:
    INFO      -> log only
    MEDIUM    -> mark source suspicious / isolate telemetry source
    HIGH      -> isolate source + mark telemetry untrusted
    CRITICAL  -> isolate source + mark telemetry untrusted + emergency brake

The emergency brake is intended only for critical integrity violations where
continuing with untrusted vehicle state could create an unsafe condition.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
import time
from threading import RLock
from typing import Any, Optional


@dataclass(frozen=True)
class ResponseAction:
    """One mitigation action selected/executed by the response engine."""

    action: str
    ecu: str
    attack_type: str
    severity: str
    reason: str
    executed: bool
    timestamp: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ResponseEngine:
    """Select and execute proportional responses to confirmed attacks."""

    def __init__(self, vcu: Optional[Any] = None) -> None:
        self.vcu = vcu
        self._lock = RLock()
        self.actions: list[ResponseAction] = []
        self.isolated_ecus: set[str] = set()
        self.untrusted_ecus: set[str] = set()
        self.emergency_brake_count = 0
        self.last_action: ResponseAction | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def handle_finding(self, finding: Any) -> list[ResponseAction]:
        """Apply response policy to a GroundTruthFinding-like object.

        The object is duck-typed to avoid coupling Blue Team response logic
        to the validator implementation.
        """
        detected = bool(getattr(finding, "detected", False))
        ecu = str(getattr(finding, "ecu", "UNKNOWN") or "UNKNOWN").upper()
        attack_type = str(getattr(finding, "attack_type", "unknown"))
        severity = str(getattr(finding, "severity", "INFO")).upper()
        reason = str(getattr(finding, "reason", "security finding"))

        if not detected:
            return [self._record("monitor", ecu, attack_type, severity, reason, True)]

        actions: list[ResponseAction] = []

        if severity == "CRITICAL":
            actions.append(self._isolate(ecu, attack_type, severity, reason))
            actions.append(self._mark_untrusted(ecu, attack_type, severity, reason))
            actions.append(self._emergency_brake(ecu, attack_type, severity, reason))
        elif severity == "HIGH":
            actions.append(self._isolate(ecu, attack_type, severity, reason))
            actions.append(self._mark_untrusted(ecu, attack_type, severity, reason))
        elif severity == "MEDIUM":
            actions.append(self._isolate(ecu, attack_type, severity, reason))
        else:
            actions.append(self._record("log_only", ecu, attack_type, severity, reason, True))

        return actions

    def isolate_ecu(self, ecu: str, *, attack_type: str = "manual", severity: str = "HIGH", reason: str = "security response") -> ResponseAction:
        return self._isolate(ecu, attack_type, severity, reason)

    def mark_untrusted(self, ecu: str, *, attack_type: str = "manual", severity: str = "HIGH", reason: str = "security response") -> ResponseAction:
        return self._mark_untrusted(ecu, attack_type, severity, reason)

    def emergency_brake(self, *, ecu: str = "VCU", attack_type: str = "manual", severity: str = "CRITICAL", reason: str = "critical security response") -> ResponseAction:
        return self._emergency_brake(ecu, attack_type, severity, reason)

    def get_action_history(self) -> list[ResponseAction]:
        with self._lock:
            return list(self.actions)

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "isolated_ecus": sorted(self.isolated_ecus),
                "untrusted_ecus": sorted(self.untrusted_ecus),
                "emergency_brake_count": self.emergency_brake_count,
                "action_count": len(self.actions),
                "last_action": self.last_action.to_dict() if self.last_action else None,
            }

    def is_ecu_trusted(self, ecu: str) -> bool:
        """Return whether telemetry from an ECU may be accepted as trusted."""
        with self._lock:
            normalized = ecu.strip().upper()
            return normalized not in self.isolated_ecus and normalized not in self.untrusted_ecus

    def clear_runtime_state(self) -> None:
        """Reset transient response state for a fresh simulation session."""
        with self._lock:
            self.actions.clear()
            self.isolated_ecus.clear()
            self.untrusted_ecus.clear()
            self.emergency_brake_count = 0
            self.last_action = None

    # ------------------------------------------------------------------
    # Action implementations
    # ------------------------------------------------------------------
    def _isolate(self, ecu: str, attack_type: str, severity: str, reason: str) -> ResponseAction:
        ecu = ecu.upper()
        with self._lock:
            self.isolated_ecus.add(ecu)
        return self._record("isolate_ecu", ecu, attack_type, severity, reason, True)

    def _mark_untrusted(self, ecu: str, attack_type: str, severity: str, reason: str) -> ResponseAction:
        ecu = ecu.upper()
        with self._lock:
            self.untrusted_ecus.add(ecu)
        return self._record("mark_untrusted", ecu, attack_type, severity, reason, True)

    def _emergency_brake(self, ecu: str, attack_type: str, severity: str, reason: str) -> ResponseAction:
        executed = False
        if self.vcu is not None:
            try:
                self.vcu.emergency_brake()
                executed = True
                with self._lock:
                    self.emergency_brake_count += 1
            except Exception as exc:  # response layer must not crash the vehicle loop
                reason = f"{reason}; emergency brake execution failed: {exc}"

        return self._record("emergency_brake", ecu.upper(), attack_type, severity, reason, executed)

    def _record(
        self,
        action: str,
        ecu: str,
        attack_type: str,
        severity: str,
        reason: str,
        executed: bool,
    ) -> ResponseAction:
        event = ResponseAction(
            action=action,
            ecu=ecu.upper(),
            attack_type=attack_type,
            severity=severity,
            reason=reason,
            executed=executed,
            timestamp=time.time(),
        )
        with self._lock:
            self.actions.append(event)
            self.last_action = event
        print(
            f"[Response Engine] {action.upper()} | ecu={event.ecu} "
            f"| severity={event.severity} | attack={event.attack_type}"
        )
        return event
