"""
ota_manager.py

Phase 3 — OTA / firmware lifecycle manager.

This is a simulation-level OTA manager. It models firmware staging,
validation, installation and rollback. Package signatures are verified by
blue_team.integrity_checker before installation is allowed.
"""

from __future__ import annotations

import hashlib
from typing import Optional

from blue_team.integrity_checker import IntegrityChecker
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

    def __init__(
        self,
        vehicle_state,
        integrity_checker: IntegrityChecker | None = None,
    ):
        super().__init__(
            ecu_id="OTA",
            vehicle_state=vehicle_state,
        )

        self.current_firmware_version = vehicle_state.firmware_version
        self.integrity_checker = integrity_checker or IntegrityChecker()
        self.pending_version: Optional[str] = None
        self.pending_package_hash: Optional[str] = None
        self.pending_package_data: Optional[bytes] = None
        self.pending_signature: Optional[str] = None
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
        signature: str,
    ) -> str:
        """Stage a firmware package for later installation.

        The signature is verified again during installation; a caller cannot
        authorize an update by supplying a boolean trust flag.
        """
        if not self.is_online():
            raise RuntimeError("OTA Manager is offline.")

        if not version or not str(version).strip():
            raise ValueError("Firmware version cannot be empty.")

        if not isinstance(package_data, (bytes, bytearray)):
            raise TypeError("package_data must be bytes or bytearray.")

        if len(package_data) == 0:
            raise ValueError("package_data cannot be empty.")
        if not isinstance(signature, str) or not signature:
            raise ValueError("A firmware signature is required.")

        self.pending_version = str(version)
        self.pending_package_data = bytes(package_data)
        self.pending_package_hash = hashlib.sha256(self.pending_package_data).hexdigest()
        self.pending_signature = signature
        self.pending_signature_valid = self.integrity_checker.verify_firmware_signature(
            self.pending_package_data, signature
        )
        self.update_state = "staged"
        self.last_error = None

        return self.pending_package_hash

    def install_update(self) -> bool:
        """Install the staged update only when its signature verifies."""
        if not self.is_online():
            raise RuntimeError("OTA Manager is offline.")

        if self.pending_version is None:
            raise RuntimeError("No firmware update is staged.")

        if (
            self.pending_package_data is None
            or self.pending_signature is None
            or not self.integrity_checker.verify_firmware_signature(
                self.pending_package_data, self.pending_signature
            )
        ):
            self.update_state = "rejected"
            self.last_error = "Firmware signature validation failed."
            self._clear_pending_update()
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
        self.pending_package_data = None
        self.pending_signature = None
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
