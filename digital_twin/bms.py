"""
bms.py

Battery Management System for the SecureEV digital twin.

Responsibilities:
    - Monitor battery State of Charge (SOC)
    - Monitor battery temperature
    - Estimate energy consumption
    - Simulate battery thermal behavior
    - Apply charging energy when a ChargingController is actively charging

The BMS remains the sole owner of battery_soc and battery_temp.
"""

from __future__ import annotations

import time

from digital_twin.base_ecu import BaseECU


class BMS(BaseECU):

    def __init__(self, vehicle_state, vcu=None, charging_controller=None):
        super().__init__(
            ecu_id="BMS",
            vehicle_state=vehicle_state,
        )

        self.vcu = vcu
        self.charging_controller = charging_controller

        self.battery_capacity_kwh = 75.0

        self.min_soc = 5.0
        self.max_soc = 100.0

        self.min_temperature = 15.0
        self.max_temperature = 60.0

        self.energy_consumed_kwh = 0.0
        self.energy_charged_kwh = 0.0

        self._previous_time = time.time()

    def update(self) -> None:
        if not self.is_online():
            return

        current_time = time.time()
        dt = current_time - self._previous_time
        self._previous_time = current_time

        if dt <= 0:
            return

        speed = max(0.0, float(self.vehicle_state.speed_kmh))
        acceleration = float(self.vehicle_state.acceleration)

        throttle = 0.0
        if self.vcu is not None:
            throttle = max(0.0, min(1.0, float(self.vcu.throttle)))

        # -----------------------------------------------------
        # Simulated EV consumption
        # -----------------------------------------------------
        base_power_kw = 1.0
        speed_power_kw = 0.025 * speed
        acceleration_power_kw = max(0.0, acceleration) * 2.0
        throttle_power_kw = throttle * 12.0

        total_power_kw = (
            base_power_kw
            + speed_power_kw
            + acceleration_power_kw
            + throttle_power_kw
        )

        consumed_kwh = total_power_kw * (dt / 3600.0)
        self.energy_consumed_kwh += consumed_kwh

        # -----------------------------------------------------
        # Optional charging input
        # -----------------------------------------------------
        charged_kwh = 0.0
        if self.charging_controller is not None:
            try:
                actively_charging = self.charging_controller.is_charging()
            except AttributeError:
                actively_charging = False

            if actively_charging:
                charge_power_kw = float(
                    self.charging_controller.charging_power_kw
                )
                charged_kwh = charge_power_kw * (dt / 3600.0)
                self.energy_charged_kwh += charged_kwh

        # Net battery energy change.
        net_energy_kwh = consumed_kwh - charged_kwh

        soc_change = (
            net_energy_kwh / self.battery_capacity_kwh
        ) * 100.0

        self.vehicle_state.battery_soc = max(
            self.min_soc,
            min(
                self.max_soc,
                self.vehicle_state.battery_soc - soc_change,
            ),
        )

        # -----------------------------------------------------
        # Battery temperature
        # -----------------------------------------------------
        thermal_load = (
            0.02 * total_power_kw
            + 0.01 * abs(acceleration)
        )

        if charged_kwh > 0:
            thermal_load += 0.01 * (
                self.charging_controller.charging_power_kw
            )

        temperature_difference = self.vehicle_state.battery_temp - 25.0
        cooling = 0.005 * temperature_difference
        temperature_change = (thermal_load - cooling) * dt

        self.vehicle_state.battery_temp = max(
            self.min_temperature,
            min(
                self.max_temperature,
                self.vehicle_state.battery_temp + temperature_change,
            ),
        )

        # Automatically stop charging once the simulated battery reaches full.
        if (
            charged_kwh > 0
            and self.vehicle_state.battery_soc >= self.max_soc
            and self.charging_controller is not None
        ):
            self.charging_controller.stop_charging()

        self.vehicle_state.last_updated = current_time

    def telemetry(self) -> dict:
        data = super().telemetry()

        data.update({
            "battery_soc": round(self.vehicle_state.battery_soc, 2),
            "battery_temp": round(self.vehicle_state.battery_temp, 2),
            "battery_capacity_kwh": self.battery_capacity_kwh,
            "energy_consumed_kwh": round(self.energy_consumed_kwh, 4),
            "energy_charged_kwh": round(self.energy_charged_kwh, 4),
        })

        return data
