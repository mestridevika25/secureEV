"""
acu.py

Autonomous Control Unit for the SecureEV digital twin.

Responsibilities:
    - Manage autonomous mode
    - Generate planned throttle
    - Generate planned brake
    - Generate planned steering
    - Maintain a target vehicle speed

The ACU does NOT communicate directly with CARLA.
CARLA interaction remains the responsibility of CarlaBridge.
"""

from __future__ import annotations

from digital_twin.base_ecu import BaseECU


class ACU(BaseECU):

    def __init__(self, vehicle_state):

        super().__init__(
            ecu_id="ACU",
            vehicle_state=vehicle_state,
        )

        self.control_mode = "MANUAL"

        self.target_speed_kmh = 0.0

        self.max_throttle = 1.0
        self.max_brake = 1.0
        self.max_steer = 1.0

    # =========================================================
    # ECU UPDATE
    # =========================================================

    def update(self) -> None:

        if not self.is_online():
            return

        # -----------------------------------------------------
        # Manual mode
        # -----------------------------------------------------

        if not self.vehicle_state.autonomous_mode:

            self.control_mode = "MANUAL"

            self.vehicle_state.planned_throttle = 0.0
            self.vehicle_state.planned_brake = 0.0
            self.vehicle_state.planned_steer = 0.0

            return

        # -----------------------------------------------------
        # Autonomous mode
        # -----------------------------------------------------

        self.control_mode = "AUTONOMOUS"

        current_speed = max(
            0.0,
            float(self.vehicle_state.speed_kmh)
        )

        speed_error = (
            self.target_speed_kmh - current_speed
        )

        # -----------------------------------------------------
        # Simple speed controller
        # -----------------------------------------------------

        if speed_error > 0:

            throttle = min(
                self.max_throttle,
                speed_error / 20.0
            )

            brake = 0.0

        elif speed_error < 0:

            throttle = 0.0

            brake = min(
                self.max_brake,
                abs(speed_error) / 20.0
            )

        else:

            throttle = 0.0
            brake = 0.0

        steer = 0.0

        # -----------------------------------------------------
        # Store planned controls
        # -----------------------------------------------------

        self.vehicle_state.planned_throttle = round(
            throttle,
            3
        )

        self.vehicle_state.planned_brake = round(
            brake,
            3
        )

        self.vehicle_state.planned_steer = round(
            max(
                -self.max_steer,
                min(self.max_steer, steer)
            ),
            3
        )

    # =========================================================
    # ENABLE AUTONOMOUS MODE
    # =========================================================

    def enable_autonomous_mode(
        self,
        target_speed_kmh: float
    ) -> None:

        if not self.is_online():
            raise RuntimeError(
                "ACU is offline. Autonomous mode rejected."
            )

        target_speed_kmh = max(
            0.0,
            float(target_speed_kmh)
        )

        self.target_speed_kmh = target_speed_kmh

        self.vehicle_state.autonomous_mode = True

    # =========================================================
    # DISABLE AUTONOMOUS MODE
    # =========================================================

    def disable_autonomous_mode(self) -> None:

        if not self.is_online():
            raise RuntimeError(
                "ACU is offline. Autonomous mode rejected."
            )

        self.vehicle_state.autonomous_mode = False

        self.control_mode = "MANUAL"

        self.vehicle_state.planned_throttle = 0.0
        self.vehicle_state.planned_brake = 0.0
        self.vehicle_state.planned_steer = 0.0

    # =========================================================
    # SET PLANNED CONTROL
    # =========================================================

    def set_planned_control(
        self,
        throttle: float = 0.0,
        brake: float = 0.0,
        steer: float = 0.0,
    ) -> None:

        if not self.is_online():
            raise RuntimeError(
                "ACU is offline. Planned control rejected."
            )

        throttle = max(
            0.0,
            min(
                self.max_throttle,
                float(throttle)
            )
        )

        brake = max(
            0.0,
            min(
                self.max_brake,
                float(brake)
            )
        )

        steer = max(
            -self.max_steer,
            min(
                self.max_steer,
                float(steer)
            )
        )

        self.vehicle_state.planned_throttle = round(
            throttle,
            3
        )

        self.vehicle_state.planned_brake = round(
            brake,
            3
        )

        self.vehicle_state.planned_steer = round(
            steer,
            3
        )

    # =========================================================
    # TELEMETRY
    # =========================================================

    def telemetry(self) -> dict:

        data = super().telemetry()

        data.update({
            "autonomous_mode":
                self.vehicle_state.autonomous_mode,

            "control_mode":
                self.control_mode,

            "target_speed_kmh":
                self.target_speed_kmh,

            "planned_throttle":
                self.vehicle_state.planned_throttle,

            "planned_brake":
                self.vehicle_state.planned_brake,

            "planned_steer":
                self.vehicle_state.planned_steer,
        })

        return data