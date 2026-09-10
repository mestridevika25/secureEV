"""
security_gateway.py

SecureEV Phase 5 - Security Gateway / Message Monitor.

The gateway is the policy boundary between the MQTT virtual vehicle network
and the ECU command path.  It performs deterministic checks before a message
is allowed to reach an ECU:

    MQTT
      -> topic / identity / schema / freshness / replay / sequence / policy
      -> ALLOW or BLOCK
      -> ECU command queue

The gateway never imports CARLA and never calls ECU methods directly.

Phase 5 intentionally uses deterministic security controls.  Machine-learning
anomaly detection and attack response are introduced in later phases.
"""

from __future__ import annotations

from collections import Counter, OrderedDict, deque
from dataclasses import dataclass
import math
import threading
import time
from typing import Any, Callable, Optional

from network.control_schema import VCU_COMMANDS, validate_vcu_control_message
from network.mqtt_config import VCU_CONTROL, VEHICLE_ID


@dataclass(frozen=True)
class SecurityDecision:
    """Result of one security-gateway inspection."""

    allowed: bool
    reason: str
    topic: str
    ecu: str | None
    command: str | None
    message_id: str | None
    sequence: int | None
    timestamp: float | None
    checked_at: float


@dataclass(frozen=True)
class SecurityEvent:
    """Audit event retained for the dashboard/database in later phases."""

    action: str
    reason: str
    topic: str
    ecu: str | None
    command: str | None
    message_id: str | None
    sequence: int | None
    timestamp: float | None
    checked_at: float


AlertHandler = Callable[[SecurityEvent], None]


class SecurityGateway:
    """Deterministic security gate for SecureEV MQTT control messages."""

    def __init__(
        self,
        expected_vehicle_id: str = VEHICLE_ID,
        max_message_age_seconds: float = 5.0,
        max_future_skew_seconds: float = 2.0,
        max_event_history: int = 500,
        max_seen_message_ids: int = 5000,
        alert_handler: Optional[AlertHandler] = None,
    ) -> None:
        if not expected_vehicle_id:
            raise ValueError("expected_vehicle_id cannot be empty.")
        if max_message_age_seconds <= 0:
            raise ValueError("max_message_age_seconds must be > 0.")
        if max_future_skew_seconds < 0:
            raise ValueError("max_future_skew_seconds must be >= 0.")
        if max_event_history <= 0:
            raise ValueError("max_event_history must be > 0.")
        if max_seen_message_ids <= 0:
            raise ValueError("max_seen_message_ids must be > 0.")

        self.expected_vehicle_id = expected_vehicle_id
        self.max_message_age_seconds = float(max_message_age_seconds)
        self.max_future_skew_seconds = float(max_future_skew_seconds)
        self.max_event_history = int(max_event_history)
        self.max_seen_message_ids = int(max_seen_message_ids)
        self.alert_handler = alert_handler

        self.allowed_topics = {VCU_CONTROL}
        self.allowed_commands = set(VCU_COMMANDS)

        # Sequence state is tracked independently for each protected topic.
        self._last_sequence: dict[str, int] = {}

        # Ordered replay cache: message_id -> time first accepted/observed.
        self._seen_message_ids: OrderedDict[str, float] = OrderedDict()

        self._events: deque[SecurityEvent] = deque(maxlen=self.max_event_history)
        self._reason_counts: Counter[str] = Counter()
        self._lock = threading.RLock()

        self.checked_count = 0
        self.allowed_count = 0
        self.blocked_count = 0
        self.last_decision: SecurityDecision | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def inspect(
        self,
        topic: str,
        message: dict[str, Any],
    ) -> SecurityDecision:
        """Inspect one MQTT message and return an allow/block decision.

        Only an ALLOW decision advances replay/sequence state.  A blocked
        message must never consume a legitimate sequence number.
        """

        checked_at = time.time()
        topic = str(topic)

        with self._lock:
            self.checked_count += 1

            basic = self._extract_basic_fields(message)
            ecu = basic["ecu"]
            command = basic["command"]
            message_id = basic["message_id"]
            sequence = basic["sequence"]
            timestamp = basic["timestamp"]

            # 1. Expected MQTT topic.
            if topic not in self.allowed_topics:
                return self._block(
                    reason="unexpected topic",
                    topic=topic,
                    ecu=ecu,
                    command=command,
                    message_id=message_id,
                    sequence=sequence,
                    timestamp=timestamp,
                    checked_at=checked_at,
                )

            # 2. Structural + range validation shared with Phase 4F.
            valid, reason = validate_vcu_control_message(
                message,
                expected_vehicle_id=self.expected_vehicle_id,
            )
            if not valid:
                return self._block(
                    reason=reason,
                    topic=topic,
                    ecu=ecu,
                    command=command,
                    message_id=message_id,
                    sequence=sequence,
                    timestamp=timestamp,
                    checked_at=checked_at,
                )

            # 3. Stronger type checks that are useful at the security boundary.
            protocol = message.get("protocol_version")
            if isinstance(protocol, bool) or not isinstance(protocol, int):
                return self._block(
                    reason="invalid protocol_version type",
                    topic=topic,
                    ecu=ecu,
                    command=command,
                    message_id=message_id,
                    sequence=sequence,
                    timestamp=timestamp,
                    checked_at=checked_at,
                )

            if not isinstance(sequence, int) or isinstance(sequence, bool):
                return self._block(
                    reason="invalid sequence type",
                    topic=topic,
                    ecu=ecu,
                    command=command,
                    message_id=message_id,
                    sequence=sequence if isinstance(sequence, int) else None,
                    timestamp=timestamp,
                    checked_at=checked_at,
                )

            if not isinstance(timestamp, (int, float)) or isinstance(timestamp, bool):
                return self._block(
                    reason="invalid timestamp type",
                    topic=topic,
                    ecu=ecu,
                    command=command,
                    message_id=message_id,
                    sequence=sequence,
                    timestamp=timestamp if isinstance(timestamp, (int, float)) else None,
                    checked_at=checked_at,
                )

            if not math.isfinite(float(timestamp)):
                return self._block(
                    reason="timestamp is not finite",
                    topic=topic,
                    ecu=ecu,
                    command=command,
                    message_id=message_id,
                    sequence=sequence,
                    timestamp=float(timestamp),
                    checked_at=checked_at,
                )

            if not isinstance(message_id, str) or not message_id.strip():
                return self._block(
                    reason="missing message_id",
                    topic=topic,
                    ecu=ecu,
                    command=command,
                    message_id=message_id if isinstance(message_id, str) else None,
                    sequence=sequence,
                    timestamp=timestamp,
                    checked_at=checked_at,
                )

            # 4. Command authorization.
            if command not in self.allowed_commands:
                return self._block(
                    reason="command not authorized",
                    topic=topic,
                    ecu=ecu,
                    command=command,
                    message_id=message_id,
                    sequence=sequence,
                    timestamp=timestamp,
                    checked_at=checked_at,
                )

            # 5. Freshness / anti-delay check.
            age = checked_at - float(timestamp)
            if age > self.max_message_age_seconds:
                return self._block(
                    reason="stale message",
                    topic=topic,
                    ecu=ecu,
                    command=command,
                    message_id=message_id,
                    sequence=sequence,
                    timestamp=timestamp,
                    checked_at=checked_at,
                )

            if age < -self.max_future_skew_seconds:
                return self._block(
                    reason="future-dated message",
                    topic=topic,
                    ecu=ecu,
                    command=command,
                    message_id=message_id,
                    sequence=sequence,
                    timestamp=timestamp,
                    checked_at=checked_at,
                )

            # 6. Replay detection by unique message identifier.
            if message_id in self._seen_message_ids:
                return self._block(
                    reason="replay detected",
                    topic=topic,
                    ecu=ecu,
                    command=command,
                    message_id=message_id,
                    sequence=sequence,
                    timestamp=timestamp,
                    checked_at=checked_at,
                )

            # 7. Monotonic sequence check.
            last_sequence = self._last_sequence.get(topic, 0)
            if sequence <= last_sequence:
                return self._block(
                    reason="non-monotonic sequence",
                    topic=topic,
                    ecu=ecu,
                    command=command,
                    message_id=message_id,
                    sequence=sequence,
                    timestamp=timestamp,
                    checked_at=checked_at,
                )

            # 8. All checks passed: advance security state and allow.
            self._last_sequence[topic] = sequence
            self._remember_message_id(message_id, checked_at)

            self.allowed_count += 1
            decision = SecurityDecision(
                allowed=True,
                reason="allowed",
                topic=topic,
                ecu=ecu,
                command=command,
                message_id=message_id,
                sequence=sequence,
                timestamp=float(timestamp),
                checked_at=checked_at,
            )
            self.last_decision = decision
            self._record_event(decision)
            return decision

    def get_events(self) -> list[SecurityEvent]:
        """Return a snapshot of retained security events."""
        with self._lock:
            return list(self._events)

    def get_reason_counts(self) -> dict[str, int]:
        """Return blocked-reason counters for evaluation/dashboard use."""
        with self._lock:
            return dict(self._reason_counts)

    def get_last_sequence(self, topic: str = VCU_CONTROL) -> int:
        """Return the latest accepted sequence for a protected topic."""
        with self._lock:
            return self._last_sequence.get(topic, 0)

    def reset(self) -> None:
        """Reset runtime replay/sequence state for a new vehicle session."""
        with self._lock:
            self._last_sequence.clear()
            self._seen_message_ids.clear()
            self.last_decision = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_basic_fields(message: Any) -> dict[str, Any]:
        if not isinstance(message, dict):
            return {
                "ecu": None,
                "command": None,
                "message_id": None,
                "sequence": None,
                "timestamp": None,
            }

        data = message.get("data")
        command = None
        if isinstance(data, dict) and data.get("command") is not None:
            command = str(data.get("command")).strip().lower()

        ecu_value = message.get("ecu")
        ecu = str(ecu_value).strip().upper() if ecu_value is not None else None

        return {
            "ecu": ecu,
            "command": command,
            "message_id": message.get("message_id"),
            "sequence": message.get("sequence"),
            "timestamp": message.get("timestamp"),
        }

    def _block(
        self,
        *,
        reason: str,
        topic: str,
        ecu: str | None,
        command: str | None,
        message_id: str | None,
        sequence: int | None,
        timestamp: float | None,
        checked_at: float,
    ) -> SecurityDecision:
        self.blocked_count += 1

        decision = SecurityDecision(
            allowed=False,
            reason=reason,
            topic=topic,
            ecu=ecu,
            command=command,
            message_id=message_id,
            sequence=sequence,
            timestamp=timestamp,
            checked_at=checked_at,
        )
        self.last_decision = decision
        self._record_event(decision)
        return decision

    def _record_event(self, decision: SecurityDecision) -> None:
        action = "ALLOW" if decision.allowed else "BLOCK"
        event = SecurityEvent(
            action=action,
            reason=decision.reason,
            topic=decision.topic,
            ecu=decision.ecu,
            command=decision.command,
            message_id=decision.message_id,
            sequence=decision.sequence,
            timestamp=decision.timestamp,
            checked_at=decision.checked_at,
        )
        self._events.append(event)

        if not decision.allowed:
            self._reason_counts[decision.reason] += 1
            print(
                f"[Security Gateway] BLOCK | reason={decision.reason} "
                f"| topic={decision.topic} | sequence={decision.sequence}"
            )
        else:
            print(
                f"[Security Gateway] ALLOW | command={decision.command} "
                f"| sequence={decision.sequence}"
            )

        if self.alert_handler is not None:
            try:
                self.alert_handler(event)
            except Exception as exc:
                print(f"[Security Gateway] Alert handler error: {exc}")

    def _remember_message_id(self, message_id: str, observed_at: float) -> None:
        self._seen_message_ids[message_id] = observed_at
        self._seen_message_ids.move_to_end(message_id)

        while len(self._seen_message_ids) > self.max_seen_message_ids:
            self._seen_message_ids.popitem(last=False)
