"""
bcm.py

Body Control Module for the SecureEV digital twin.

Ownership:
    - doors_locked
    - doors_open

The BCM simulates vehicle body-access functions such as
locking, unlocking, opening and closing the doors.
"""

from __future__ import annotations

from digital_twin.base_ecu import BaseECU


class BCM(BaseECU):

    def __init__(self, vehicle_state):

        super().__init__(
            ecu_id="BCM",
            vehicle_state=vehicle_state,
        )

    # ---------------------------------------------------------
    # ECU update
    # ---------------------------------------------------------

    def update(self) -> None:
        """
        Maintain BCM-related state.

        At this stage the BCM does not need a continuous
        physical calculation. Its state changes through
        explicit commands.
        """

        if not self.is_online():
            return

        # Safety rule:
        # A locked vehicle should not remain in the "doors open"
        # state in our simplified digital-twin model.
        if self.vehicle_state.doors_locked:
            self.vehicle_state.doors_open = False

    # ---------------------------------------------------------
    # Door commands
    # ---------------------------------------------------------

    def lock_doors(self) -> None:

        if not self.is_online():
            raise RuntimeError(
                "BCM is offline. Door lock command rejected."
            )

        self.vehicle_state.doors_locked = True
        self.vehicle_state.doors_open = False

    def unlock_doors(self) -> None:

        if not self.is_online():
            raise RuntimeError(
                "BCM is offline. Door unlock command rejected."
            )

        self.vehicle_state.doors_locked = False

    def open_doors(self) -> None:

        if not self.is_online():
            raise RuntimeError(
                "BCM is offline. Door open command rejected."
            )

        if self.vehicle_state.doors_locked:
            raise RuntimeError(
                "Doors are locked. Unlock the vehicle first."
            )

        self.vehicle_state.doors_open = True

    def close_doors(self) -> None:

        if not self.is_online():
            raise RuntimeError(
                "BCM is offline. Door close command rejected."
            )

        self.vehicle_state.doors_open = False

    # ---------------------------------------------------------
    # Telemetry
    # ---------------------------------------------------------

    def telemetry(self) -> dict:

        data = super().telemetry()

        data.update({
            "doors_locked": self.vehicle_state.doors_locked,
            "doors_open": self.vehicle_state.doors_open,
        })

        return data