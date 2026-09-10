"""
data_spoofing.py

SecureEV Phase 6B - controlled Red Team telemetry/data-spoofing attacks.

These attacks deliberately publish false ECU telemetry onto the MQTT virtual
vehicle network.  They do not import CARLA and do not alter CARLA physics.
The purpose of Phase 6B is to create a repeatable, measurable false-data
condition that Phase 7 can validate against CARLA ground truth.

Scenarios:
    1. speed_spoofing  -> VCU reports an impossible/fake speed
    2. battery_soc_spoofing -> BMS reports a false battery SOC
    3. gps_spoofing -> TCU reports a false location

Phase 5 currently protects the VCU control path, not telemetry. Therefore,
these messages are expected to reach the MQTT observer in this phase. That is
intentional: Phase 7 will use CARLA as the trusted reference to detect the
mismatch, and later phases will add the response/mitigation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from network.message_schema import create_message
from network.mqtt_config import (
    BMS_TELEMETRY,
    TCU_TELEMETRY,
    VCU_TELEMETRY,
    VEHICLE_ID,
)
from network.publisher import MQTTPublisher


@dataclass(frozen=True)
class TelemetrySpoofScenario:
    """One controlled telemetry-spoofing attack."""

    name: str
    ecu: str
    topic: str
    message: dict[str, Any]
    expected_field: str
    expected_value: Any
    description: str


class DataSpoofingAttacker:
    """Publish controlled false telemetry through the normal MQTT path."""

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

    def _message(
        self,
        ecu: str,
        data: dict[str, Any],
        sequence: int,
    ) -> dict[str, Any]:
        return create_message(
            ecu=ecu,
            message_type="telemetry",
            data=data,
            sequence=sequence,
            vehicle_id=self.vehicle_id,
        )

    def speed_spoofing(
        self,
        sequence: int = 1,
        spoofed_speed_kmh: float = 180.0,
    ) -> TelemetrySpoofScenario:
        """Publish a false VCU speed without changing the physical vehicle."""
        message = self._message(
            "VCU",
            {
                "speed_kmh": float(spoofed_speed_kmh),
                "acceleration_mps2": 0.0,
                "throttle": 0.0,
                "brake": 0.0,
                "steer": 0.0,
            },
            sequence,
        )

        return TelemetrySpoofScenario(
            name="speed_spoofing",
            ecu="VCU",
            topic=VCU_TELEMETRY,
            message=message,
            expected_field="speed_kmh",
            expected_value=float(spoofed_speed_kmh),
            description="Fake VCU speed is injected while CARLA remains stationary.",
        )

    def battery_soc_spoofing(
        self,
        sequence: int = 1,
        spoofed_soc: float = 99.0,
    ) -> TelemetrySpoofScenario:
        """Publish a false BMS battery state."""
        message = self._message(
            "BMS",
            {
                "battery_soc": float(spoofed_soc),
                "battery_temp": 25.0,
                "battery_capacity_kwh": 75.0,
                "energy_consumed_kwh": 0.0,
                "energy_charged_kwh": 0.0,
            },
            sequence,
        )

        return TelemetrySpoofScenario(
            name="battery_soc_spoofing",
            ecu="BMS",
            topic=BMS_TELEMETRY,
            message=message,
            expected_field="battery_soc",
            expected_value=float(spoofed_soc),
            description="False BMS state-of-charge is published to the vehicle network.",
        )

    def gps_spoofing(
        self,
        sequence: int = 1,
        spoofed_location: dict[str, float] | None = None,
    ) -> TelemetrySpoofScenario:
        """Publish a false TCU position."""
        if spoofed_location is None:
            spoofed_location = {
                "x": 99999.0,
                "y": -99999.0,
                "z": 10.0,
            }

        location = {
            "x": float(spoofed_location["x"]),
            "y": float(spoofed_location["y"]),
            "z": float(spoofed_location["z"]),
        }

        message = self._message(
            "TCU",
            {
                "reported_gps": location,
                "gps_source": "GNSS",
            },
            sequence,
        )

        return TelemetrySpoofScenario(
            name="gps_spoofing",
            ecu="TCU",
            topic=TCU_TELEMETRY,
            message=message,
            expected_field="reported_gps",
            expected_value=location,
            description="False TCU location is injected without moving the CARLA vehicle.",
        )

    def publish_attack(self, scenario: TelemetrySpoofScenario) -> bool:
        """Publish one controlled telemetry spoofing scenario."""
        if not isinstance(scenario, TelemetrySpoofScenario):
            raise TypeError("scenario must be TelemetrySpoofScenario.")

        return self.publisher.publish(
            scenario.topic,
            scenario.message,
            qos=1,
        )
