"""
ecu_telemetry_bridge.py

SecureEV Phase 4C/D - ECU telemetry -> MQTT bridge.

This module deliberately keeps MQTT out of the ECU classes. ECUs remain
Digital Twin components, while this bridge transports their reported
telemetry onto the virtual vehicle network.
"""

from __future__ import annotations

from typing import Any

from network.message_schema import create_message
from network.mqtt_config import VEHICLE_ID, VCU_TELEMETRY
from network.publisher import MQTTPublisher


class ECUTelemetryBridge:
    """Publish ECU telemetry without coupling ECU implementations to MQTT."""

    def __init__(
        self,
        publisher: MQTTPublisher,
        vehicle_id: str = VEHICLE_ID,
    ) -> None:
        if publisher is None:
            raise ValueError("publisher cannot be None.")

        if not vehicle_id:
            raise ValueError("vehicle_id cannot be empty.")

        self.publisher = publisher
        self.vehicle_id = vehicle_id
        self._sequences: dict[str, int] = {}

    def next_sequence(self, ecu_id: str) -> int:
        """Return the next monotonically increasing sequence for an ECU."""
        ecu_id = str(ecu_id).strip().upper()

        if not ecu_id:
            raise ValueError("ecu_id cannot be empty.")

        current = self._sequences.get(ecu_id, 0)
        self._sequences[ecu_id] = current + 1
        return current + 1

    def publish_telemetry(
        self,
        ecu_id: str,
        topic: str,
        telemetry: dict[str, Any],
    ) -> bool:
        """Wrap ECU telemetry in the common SecureEV MQTT envelope."""
        if not isinstance(telemetry, dict):
            raise TypeError("telemetry must be a dictionary.")

        sequence = self.next_sequence(ecu_id)

        message = create_message(
            ecu=ecu_id,
            message_type="telemetry",
            data=dict(telemetry),
            sequence=sequence,
            vehicle_id=self.vehicle_id,
        )

        return self.publisher.publish(
            topic,
            message,
            qos=1,
        )

    def publish_vcu(self, telemetry: dict[str, Any]) -> bool:
        """Publish one VCU telemetry snapshot."""
        return self.publish_telemetry(
            ecu_id="VCU",
            topic=VCU_TELEMETRY,
            telemetry=telemetry,
        )
