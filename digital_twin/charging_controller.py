"""
charging_controller.py

Phase 3 — EV Charging Controller.

Owns:
    - charging_state
    - charge_port_locked
    - vehicle_disabled_flag

This module models the charging-session state machine. It does not directly
modify battery SOC; BMS remains the owner of battery_soc and consumes the
charging state/power information exposed by this controller.
"""

from __future__ import annotations

from digital_twin.base_ecu import BaseECU


class ChargingController(BaseECU):
    """Simulated EV charging controller."""

    VALID_STATES = {"idle", "charging", "fault"}

    def __init__(self, vehicle_state, charging_power_kw: float = 11.0):
        super().__init__(
            ecu_id="CHG",
            vehicle_state=vehicle_state,
        )

        if charging_power_kw <= 0:
            raise ValueError("charging_power_kw must be greater than zero.")

        self.charging_power_kw = float(charging_power_kw)
        self.charger_connected = False
        self.fault_reason = None
        self.last_command = "initialized"

        self.vehicle_state.charging_state = "idle"
        self.vehicle_state.charge_port_locked = True
        self.vehicle_state.vehicle_disabled_flag = False

    def update(self) -> None:
        """Keep charging state internally consistent."""

        if not self.is_online():
            return

        state = self.vehicle_state.charging_state

        if state not in self.VALID_STATES:
            self.vehicle_state.charging_state = "fault"
            self.fault_reason = "Invalid charging state detected."
            return

        if state == "charging":
            if not self.charger_connected:
                self.vehicle_state.charging_state = "fault"
                self.fault_reason = "Charging was active without a charger."
            elif not self.vehicle_state.charge_port_locked:
                self.vehicle_state.charging_state = "fault"
                self.fault_reason = "Charging port became unlocked during charging."

    def connect_charger(self) -> None:
        if not self.is_online():
            raise RuntimeError("Charging Controller is offline.")

        if self.vehicle_state.vehicle_disabled_flag:
            raise RuntimeError("Vehicle is disabled. Charging connection rejected.")

        self.charger_connected = True
        self.vehicle_state.charge_port_locked = True
        self.vehicle_state.charging_state = "idle"
        self.fault_reason = None
        self.last_command = "charger_connected"

    def disconnect_charger(self) -> None:
        if not self.is_online():
            raise RuntimeError("Charging Controller is offline.")

        self.vehicle_state.charging_state = "idle"
        self.charger_connected = False
        self.fault_reason = None
        self.last_command = "charger_disconnected"

    def lock_port(self) -> None:
        if not self.is_online():
            raise RuntimeError("Charging Controller is offline.")

        self.vehicle_state.charge_port_locked = True
        self.last_command = "port_locked"

    def unlock_port(self) -> None:
        if not self.is_online():
            raise RuntimeError("Charging Controller is offline.")

        if self.vehicle_state.charging_state == "charging":
            raise RuntimeError("Cannot unlock the charge port while charging.")

        self.vehicle_state.charge_port_locked = False
        self.last_command = "port_unlocked"

    def start_charging(self) -> None:
        if not self.is_online():
            raise RuntimeError("Charging Controller is offline.")

        if self.vehicle_state.vehicle_disabled_flag:
            raise RuntimeError("Vehicle is disabled. Charging cannot start.")

        if self.vehicle_state.battery_soc >= 100.0:
            raise RuntimeError("Battery is already full.")

        if self.vehicle_state.charging_state == "fault":
            raise RuntimeError("Charging Controller is in FAULT state.")

        if not self.charger_connected:
            raise RuntimeError("No charger is connected.")

        if not self.vehicle_state.charge_port_locked:
            raise RuntimeError("Charge port must be locked before charging.")

        self.vehicle_state.charging_state = "charging"
        self.fault_reason = None
        self.last_command = "charging_started"

    def stop_charging(self) -> None:
        if not self.is_online():
            raise RuntimeError("Charging Controller is offline.")

        self.vehicle_state.charging_state = "idle"
        self.last_command = "charging_stopped"

    def set_fault(self, reason: str = "Charging fault") -> None:
        if not self.is_online():
            raise RuntimeError("Charging Controller is offline.")

        self.vehicle_state.charging_state = "fault"
        self.fault_reason = str(reason)
        self.last_command = "fault_set"

    def clear_fault(self) -> None:
        if not self.is_online():
            raise RuntimeError("Charging Controller is offline.")

        self.vehicle_state.charging_state = "idle"
        self.fault_reason = None
        self.last_command = "fault_cleared"

    def disable_vehicle(self, reason: str = "Vehicle disabled") -> None:
        """Place the vehicle into an immobilized safety state."""
        if not self.is_online():
            raise RuntimeError("Charging Controller is offline.")

        self.vehicle_state.vehicle_disabled_flag = True
        self.vehicle_state.charging_state = "idle"
        self.last_command = f"vehicle_disabled: {reason}"

    def enable_vehicle(self) -> None:
        if not self.is_online():
            raise RuntimeError("Charging Controller is offline.")

        self.vehicle_state.vehicle_disabled_flag = False
        self.last_command = "vehicle_enabled"

    def is_charging(self) -> bool:
        return (
            self.vehicle_state.charging_state == "charging"
            and self.charger_connected
        )

    def telemetry(self) -> dict:
        data = super().telemetry()
        data.update({
            "charging_state": self.vehicle_state.charging_state,
            "charger_connected": self.charger_connected,
            "charge_port_locked": self.vehicle_state.charge_port_locked,
            "charging_power_kw": self.charging_power_kw,
            "vehicle_disabled_flag": self.vehicle_state.vehicle_disabled_flag,
            "fault_reason": self.fault_reason,
            "last_command": self.last_command,
        })
        return data
