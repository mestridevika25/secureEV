"""
control_bridge.py

SecureEV MQTT -> Security Gateway -> VCU command bridge.

MQTT callbacks run on the Paho network thread.  Messages are first passed
through the Phase 5 SecurityGateway.  Only ALLOW decisions are queued and the
queue is drained by the main simulation thread, which keeps CARLA/VCU calls
out of the MQTT callback thread.
"""

from __future__ import annotations

from dataclasses import dataclass
from queue import Empty, Queue
from typing import Any

from blue_team.security_gateway import SecurityGateway
from digital_twin.vcu import VCU
from network.mqtt_config import CONTROL_WILDCARD, VCU_CONTROL, VEHICLE_ID
from network.subscriber import MQTTSubscriber


@dataclass(frozen=True)
class PendingCommand:
    topic: str
    message: dict[str, Any]


class MQTTControlBridge:
    """Receive MQTT VCU commands through the Phase 5 security gateway."""

    def __init__(
        self,
        vcu: VCU,
        subscriber: MQTTSubscriber,
        vehicle_id: str = VEHICLE_ID,
        security_gateway: SecurityGateway | None = None,
    ) -> None:
        if vcu is None:
            raise ValueError("vcu cannot be None.")
        if subscriber is None:
            raise ValueError("subscriber cannot be None.")

        self.vcu = vcu
        self.subscriber = subscriber
        self.vehicle_id = vehicle_id
        self.security_gateway = security_gateway or SecurityGateway(
            expected_vehicle_id=vehicle_id,
        )
        self._queue: Queue[PendingCommand] = Queue()

        # Bridge-level counters. The gateway owns the security counters.
        self.received_count = 0
        self.accepted_count = 0
        self.rejected_count = 0
        self.last_rejection_reason: str | None = None
        self.last_command: str | None = None

    def _on_message(self, topic: str, payload: dict[str, Any]) -> None:
        self.received_count += 1

        decision = self.security_gateway.inspect(topic, payload)
        if not decision.allowed:
            self.rejected_count += 1
            self.last_rejection_reason = decision.reason
            return

        # The gateway has already checked that this is a VCU control message.
        if topic != VCU_CONTROL:
            # Defensive guard in case the gateway policy changes later.
            self.rejected_count += 1
            self.last_rejection_reason = "gateway allowed non-VCU topic"
            return

        self.accepted_count += 1
        self.last_command = str(payload["data"]["command"])
        self._queue.put(
            PendingCommand(
                topic=topic,
                message=payload,
            )
        )

    def start(self) -> bool:
        """Attach callback and subscribe to the control surface."""

        self.subscriber.message_handler = self._on_message

        if not self.subscriber.connected:
            if not self.subscriber.connect():
                return False

        # Subscribe to all control topics so the gateway can detect an
        # unexpected topic instead of silently ignoring it.
        return self.subscriber.subscribe(CONTROL_WILDCARD, qos=1)

    def process_pending_commands(
        self,
        max_commands: int = 10,
        command_filter: Any | None = None,
    ) -> int:
        """Apply queued commands from the main simulation thread."""

        if max_commands <= 0:
            return 0

        processed = 0

        while processed < max_commands:
            try:
                pending = self._queue.get_nowait()
            except Empty:
                break

            try:
                if command_filter is not None and not command_filter(pending.message):
                    continue
                self._apply_command(pending.message)
            finally:
                self._queue.task_done()

            processed += 1

        return processed

    def _apply_command(self, message: dict[str, Any]) -> None:
        data = message["data"]
        command = str(data["command"]).strip().lower()

        if command == "emergency_brake":
            self.vcu.emergency_brake()
            print("[VCU Control] Emergency brake applied.")
            return

        if command == "set_control":
            self.vcu.apply_command(
                throttle=float(data["throttle"]),
                brake=float(data["brake"]),
                steer=float(data["steer"]),
            )
            return

        # The SecurityGateway + control schema should make this unreachable.
        raise ValueError(f"Unsupported command: {command}")

    def pending_count(self) -> int:
        return self._queue.qsize()

    def clear_pending_commands(self) -> int:
        """Discard commands received before a recovery boundary."""
        cleared = 0
        while True:
            try:
                self._queue.get_nowait()
            except Empty:
                return cleared
            else:
                self._queue.task_done()
                cleared += 1
