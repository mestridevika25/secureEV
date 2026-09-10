"""
base_ecu.py

Phase 2 — Base ECU abstraction.

Every simulated ECU inherits from BaseECU.

Design goals:
- Every ECU has a stable identifier.
- Every ECU shares the same VehicleState object.
- Every ECU has an ONLINE/OFFLINE state.
- Every ECU exposes telemetry.
- ECU-specific behavior is implemented in subclasses.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseECU(ABC):
    """Base class for all SecureEV digital-twin ECUs."""

    VALID_STATUSES = {"ONLINE", "OFFLINE", "FAULT"}

    def __init__(self, ecu_id: str, vehicle_state):
        if not ecu_id:
            raise ValueError("ecu_id cannot be empty.")

        if vehicle_state is None:
            raise ValueError("vehicle_state cannot be None.")

        self.ecu_id = ecu_id
        self.vehicle_state = vehicle_state

        self.status = "ONLINE"
        self.last_update_time = time.time()
        self.update_count = 0

    @abstractmethod
    def update(self) -> None:
        """
        Update ECU-owned fields.

        Each concrete ECU implements its own logic.
        """
        raise NotImplementedError

    def set_status(self, status: str) -> None:
        status = status.upper()

        if status not in self.VALID_STATUSES:
            raise ValueError(
                f"Invalid ECU status '{status}'. "
                f"Allowed: {sorted(self.VALID_STATUSES)}"
            )

        self.status = status

    def is_online(self) -> bool:
        return self.status == "ONLINE"

    def telemetry(self) -> Dict[str, Any]:
        """
        Base telemetry.

        Child ECUs should extend this dictionary with
        their ECU-specific measurements.
        """
        return {
            "ecu_id": self.ecu_id,
            "status": self.status,
            "timestamp": time.time(),
            "last_update_time": self.last_update_time,
            "update_count": self.update_count,
        }

    def tick(self) -> Dict[str, Any]:
        """
        Execute one simulation tick.

        Returns telemetry after the update.
        """
        if not self.is_online():
            return self.telemetry()

        self.update()

        self.last_update_time = time.time()
        self.update_count += 1

        return self.telemetry()

    def __str__(self) -> str:
        return f"{self.ecu_id} [{self.status}]"