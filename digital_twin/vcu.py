"""
vcu.py

Vehicle Control Unit.

Ownership:
    - speed_kmh
    - acceleration

The VCU obtains trusted physical measurements through CarlaBridge.

IMPORTANT:
VCU never imports CARLA directly.
Only CarlaBridge communicates with CARLA.
"""

from __future__ import annotations

import time

from digital_twin.base_ecu import BaseECU


class VCU(BaseECU):

    def __init__(self, vehicle_state, carla_bridge):
        super().__init__(
            ecu_id="VCU",
            vehicle_state=vehicle_state,
        )

        if carla_bridge is None:
            raise ValueError("carla_bridge cannot be None.")

        self.carla_bridge = carla_bridge

        self.throttle = 0.0
        self.brake = 0.0
        self.steer = 0.0

        self._previous_speed_kmh = None
        self._previous_time = None

    def update(self) -> None:
        """Synchronize VCU state with trusted CARLA ground truth."""

        if not self.is_online():
            return

        ground_truth = self.carla_bridge.get_ground_truth_state()

        current_speed = float(ground_truth["speed_kmh"])
        current_time = float(ground_truth["timestamp"])

        # Calculate acceleration from consecutive ground-truth samples.
        acceleration = 0.0

        if (
            self._previous_speed_kmh is not None
            and self._previous_time is not None
        ):
            dt = current_time - self._previous_time

            if dt > 0:
                acceleration = (
                    (current_speed - self._previous_speed_kmh) / 3.6
                ) / dt

        self.vehicle_state.speed_kmh = round(current_speed, 2)
        self.vehicle_state.acceleration = round(acceleration, 3)

        self.vehicle_state.last_updated = current_time

        self._previous_speed_kmh = current_speed
        self._previous_time = current_time

    def apply_command(
        self,
        throttle: float = 0.0,
        brake: float = 0.0,
        steer: float = 0.0,
    ) -> None:

        if not self.is_online():
            raise RuntimeError("VCU is offline. Control command rejected.")

        throttle = max(0.0, min(1.0, float(throttle)))
        brake = max(0.0, min(1.0, float(brake)))
        steer = max(-1.0, min(1.0, float(steer)))

        self.throttle = throttle
        self.brake = brake
        self.steer = steer

        self.carla_bridge.apply_control(
            throttle=throttle,
            brake=brake,
            steer=steer,
        )

    def emergency_brake(self) -> None:
        """Immediately stop the EV through the trusted CARLA bridge.

        The bridge first disables Traffic Manager autopilot so the autonomous
        controller cannot overwrite the safety brake on the next simulator
        update.
        """

        self.throttle = 0.0
        self.brake = 1.0
        self.steer = 0.0

        emergency_stop = getattr(self.carla_bridge, "emergency_stop", None)
        if callable(emergency_stop):
            emergency_stop()
            return

        self.apply_command(
            throttle=0.0,
            brake=1.0,
            steer=0.0,
        )

    def telemetry(self) -> dict:
        data = super().telemetry()

        data.update({
            "speed_kmh": self.vehicle_state.speed_kmh,
            "acceleration_mps2": self.vehicle_state.acceleration,
            "throttle": self.throttle,
            "brake": self.brake,
            "steer": self.steer,
        })

        return data