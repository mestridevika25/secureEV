"""
digital_twin_manager.py

Coordinates all SecureEV digital-twin ECUs.

The manager owns the simulation loop.
Individual ECUs own their own state updates.

CARLA communication remains isolated inside CarlaBridge.
"""

from __future__ import annotations

import time
from typing import Dict

from digital_twin.base_ecu import BaseECU


class DigitalTwinManager:

    def __init__(self, vehicle_state, tick_rate_hz: float = 10.0):

        if vehicle_state is None:
            raise ValueError("vehicle_state cannot be None.")

        if tick_rate_hz <= 0:
            raise ValueError("tick_rate_hz must be greater than zero.")

        self.vehicle_state = vehicle_state
        self.tick_rate_hz = tick_rate_hz

        self.tick_interval = 1.0 / tick_rate_hz

        self.ecus: Dict[str, BaseECU] = {}

        self.running = False
        self.tick_count = 0

    # ---------------------------------------------------------
    # ECU registration
    # ---------------------------------------------------------

    def register_ecu(self, ecu: BaseECU) -> None:

        if not isinstance(ecu, BaseECU):
            raise TypeError(
                "Only BaseECU-derived objects can be registered."
            )

        if ecu.ecu_id in self.ecus:
            raise ValueError(
                f"ECU '{ecu.ecu_id}' is already registered."
            )

        self.ecus[ecu.ecu_id] = ecu

    # ---------------------------------------------------------
    # ECU lookup
    # ---------------------------------------------------------

    def get_ecu(self, ecu_id: str):

        return self.ecus.get(ecu_id)

    # ---------------------------------------------------------
    # One simulation tick
    # ---------------------------------------------------------

    def tick(self) -> dict:

        telemetry = {}

        for ecu_id, ecu in self.ecus.items():
            telemetry[ecu_id] = ecu.tick()

        self.tick_count += 1

        return telemetry

    # ---------------------------------------------------------
    # Continuous simulation
    # ---------------------------------------------------------

    def run(self, duration_seconds: float | None = None) -> None:

        self.running = True

        start_time = time.time()

        while self.running:

            tick_start = time.time()

            self.tick()

            if (
                duration_seconds is not None
                and time.time() - start_time >= duration_seconds
            ):
                break

            elapsed = time.time() - tick_start

            sleep_time = max(
                0.0,
                self.tick_interval - elapsed
            )

            time.sleep(sleep_time)

        self.running = False

    # ---------------------------------------------------------
    # Stop simulation
    # ---------------------------------------------------------

    def stop(self) -> None:
        self.running = False

    # ---------------------------------------------------------
    # Manager status
    # ---------------------------------------------------------

    def status(self) -> dict:

        return {
            "running": self.running,
            "tick_count": self.tick_count,
            "tick_rate_hz": self.tick_rate_hz,
            "ecu_count": len(self.ecus),
            "ecus": {
                ecu_id: ecu.status
                for ecu_id, ecu in self.ecus.items()
            },
        }