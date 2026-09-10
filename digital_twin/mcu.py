"""
mcu.py

Motor Control Unit for the SecureEV digital twin.

Ownership:
    - motor_temp
    - motor_rpm

The MCU derives motor behavior from the vehicle's current
VCU operating conditions.
"""

from __future__ import annotations

import time

from digital_twin.base_ecu import BaseECU


class MCU(BaseECU):

    def __init__(self, vehicle_state, vcu=None):

        super().__init__(
            ecu_id="MCU",
            vehicle_state=vehicle_state,
        )

        self.vcu = vcu

        # Simplified motor model
        self.max_rpm = 12000.0
        self.max_motor_temperature = 120.0
        self.min_motor_temperature = 20.0

        self._previous_time = time.time()

    def update(self) -> None:

        if not self.is_online():
            return

        now = time.time()
        dt = now - self._previous_time
        self._previous_time = now

        if dt <= 0:
            return

        # -----------------------------------------------------
        # Read VCU operating conditions
        # -----------------------------------------------------

        speed = max(
            0.0,
            float(self.vehicle_state.speed_kmh)
        )

        acceleration = float(
            self.vehicle_state.acceleration
        )

        throttle = 0.0

        if self.vcu is not None:
            throttle = max(
                0.0,
                min(1.0, float(self.vcu.throttle))
            )

        # -----------------------------------------------------
        # Motor RPM model
        # -----------------------------------------------------
        #
        # Approximation:
        # vehicle speed is mapped to motor RPM.
        #

        speed_rpm = (speed / 120.0) * self.max_rpm

        throttle_rpm = throttle * 1000.0

        rpm = min(
            self.max_rpm,
            max(0.0, speed_rpm + throttle_rpm)
        )

        self.vehicle_state.motor_rpm = round(
            rpm,
            2
        )

        # -----------------------------------------------------
        # Motor temperature model
        # -----------------------------------------------------

        load_factor = (
            (rpm / self.max_rpm) * 2.0
            + throttle * 3.0
            + abs(acceleration) * 0.05
        )

        cooling = (
            0.02
            * (self.vehicle_state.motor_temp - 25.0)
        )

        temperature_change = (
            load_factor - cooling
        ) * dt

        new_temperature = (
            self.vehicle_state.motor_temp
            + temperature_change
        )

        self.vehicle_state.motor_temp = max(
            self.min_motor_temperature,
            min(
                self.max_motor_temperature,
                new_temperature
            )
        )

        self.vehicle_state.last_updated = now

    def telemetry(self) -> dict:

        data = super().telemetry()

        data.update({
            "motor_rpm": round(
                self.vehicle_state.motor_rpm,
                2
            ),
            "motor_temp": round(
                self.vehicle_state.motor_temp,
                2
            ),
        })

        return data