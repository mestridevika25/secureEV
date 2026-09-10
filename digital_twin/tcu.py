"""
tcu.py

Telematics Control Unit for the SecureEV digital twin.

Responsibilities:
    - Maintain the vehicle's reported GPS position.
    - Read trusted physical position through CarlaBridge.
    - Keep reported GPS separate from CARLA ground truth.

Security relevance:
    Later, Red Team can manipulate reported_gps while
    CarlaBridge continues to provide trusted ground truth.
    Blue Team can compare the two values to detect spoofing.
"""

from __future__ import annotations

import time

from digital_twin.base_ecu import BaseECU


class TCU(BaseECU):

    def __init__(self, vehicle_state, carla_bridge):

        super().__init__(
            ecu_id="TCU",
            vehicle_state=vehicle_state,
        )

        if carla_bridge is None:
            raise ValueError(
                "carla_bridge cannot be None."
            )

        self.carla_bridge = carla_bridge

        self.gps_source = "CARLA"

        self._previous_update = time.time()

    # ---------------------------------------------------------
    # ECU update
    # ---------------------------------------------------------

    def update(self) -> None:

        if not self.is_online():
            return

        ground_truth = (
            self.carla_bridge.get_ground_truth_state()
        )

        location = ground_truth["location"]

        self.vehicle_state.reported_gps = {
            "x": round(float(location["x"]), 2),
            "y": round(float(location["y"]), 2),
            "z": round(float(location["z"]), 2),
            "source": self.gps_source,
            "timestamp": ground_truth["timestamp"],
        }

        self.vehicle_state.last_updated = (
            ground_truth["timestamp"]
        )

        self._previous_update = time.time()

    # ---------------------------------------------------------
    # GPS source configuration
    # ---------------------------------------------------------

    def set_gps_source(self, source: str) -> None:

        source = source.strip().upper()

        if not source:
            raise ValueError(
                "GPS source cannot be empty."
            )

        self.gps_source = source

    # ---------------------------------------------------------
    # Telemetry
    # ---------------------------------------------------------

    def telemetry(self) -> dict:

        data = super().telemetry()

        data.update({
            "reported_gps": self.vehicle_state.reported_gps,
            "gps_source": self.gps_source,
        })

        return data