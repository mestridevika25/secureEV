"""
ota_manager.py

Phase 3 — OTA / firmware lifecycle manager.

This is a simulation-level OTA manager. It models firmware staging,
validation, installation and rollback. The cryptographic signature check is
intentionally represented by a boolean input for now; the real security
verification belongs in blue_team/integrity_checker.py and will be replaced
with a cryptographic implementation in a later security phase.
"""

from __future__ import annotations

import hashlib
from typing import Optional

from digital_twin.base_ecu import BaseECU


class OTAManager(BaseECU):
    """Simulated vehicle OTA firmware manager."""

    VALID_STATES = {
        "idle",
        "staged",
        "installing",
        "success",
        "rejected",
        "failed",
    }

    def __init__(self, vehicle_state):
        super().__init__(
            ecu_id="OTA",
            vehicle_state=vehicle_state,
        )

        self.current_firmware_version = vehicle_state.firmware_version
        self.pending_version: Optional[str] = None
        self.pending_package_hash: Optional[str] = None
        self.pending_signature_valid: Optional[bool] = None
        self.previous_firmware_version: Optional[str] = None
        self.update_state = "idle"
        self.last_error: Optional[str] = None

    def update(self) -> None:
        if not self.is_online():
            return

        if self.update_state not in self.VALID_STATES:
            self.update_state = "failed"
            self.last_error = "Invalid OTA state."

    def stage_update(
        self,
        version: str,
        package_data: bytes,
        signature_valid: bool,
    ) -> str:
        """Stage a firmware package for later installation.

        ``signature_valid`` is a simulation input only. It is deliberately
        kept separate from the actual package hash so that the Blue Team can
        later perform the real signature verification step.
        """
        if not self.is_online():
            raise RuntimeError("OTA Manager is offline.")

        if not version or not str(version).strip():
            raise ValueError("Firmware version cannot be empty.")

        if not isinstance(package_data, (bytes, bytearray)):
            raise TypeError("package_data must be bytes or bytearray.")

        if len(package_data) == 0:
            raise ValueError("package_data cannot be empty.")

        self.pending_version = str(version)
        self.pending_package_hash = hashlib.sha256(
            bytes(package_data)
        ).hexdigest()
        self.pending_signature_valid = bool(signature_valid)
        self.update_state = "staged"
        self.last_error = None

        return self.pending_package_hash

    def install_update(self) -> bool:
        """Install the staged update only when the simulated signature gate passes."""
        if not self.is_online():
            raise RuntimeError("OTA Manager is offline.")

        if self.pending_version is None:
            raise RuntimeError("No firmware update is staged.")

        if self.pending_signature_valid is not True:
            self.update_state = "rejected"
            self.last_error = "Firmware signature validation failed."
            return False

        self.update_state = "installing"
        self.previous_firmware_version = self.current_firmware_version

        self.current_firmware_version = self.pending_version
        self.vehicle_state.firmware_version = self.pending_version

        self.update_state = "success"
        self.last_error = None

        self._clear_pending_update()
        return True

    def reject_update(self, reason: str = "Update rejected") -> None:
        if not self.is_online():
            raise RuntimeError("OTA Manager is offline.")

        self.update_state = "rejected"
        self.last_error = str(reason)
        self._clear_pending_update()

    def rollback(self) -> bool:
        if not self.is_online():
            raise RuntimeError("OTA Manager is offline.")

        if self.previous_firmware_version is None:
            self.update_state = "failed"
            self.last_error = "No previous firmware version available."
            return False

        self.current_firmware_version = self.previous_firmware_version
        self.vehicle_state.firmware_version = self.previous_firmware_version
        self.update_state = "success"
        self.last_error = None
        return True

    def _clear_pending_update(self) -> None:
        self.pending_version = None
        self.pending_package_hash = None
        self.pending_signature_valid = None

    def telemetry(self) -> dict:
        data = super().telemetry()
        data.update({
            "firmware_version": self.vehicle_state.firmware_version,
            "update_state": self.update_state,
            "pending_version": self.pending_version,
            "pending_package_hash": self.pending_package_hash,
            "pending_signature_valid": self.pending_signature_valid,
            "previous_firmware_version": self.previous_firmware_version,
            "last_error": self.last_error,
        })
        return data
