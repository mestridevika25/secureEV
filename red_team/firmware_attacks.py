"""Controlled firmware-tampering scenarios for the local SecureEV simulation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FirmwareAttackScenario:
    name: str
    version: str
    package: bytes
    signature: str
    description: str


class FirmwareAttacker:
    """Create corrupted or forged update packages without installing them."""

    def cloud_update_attack(
        self,
        version: str,
        trusted_package: bytes,
        trusted_signature: str,
    ) -> FirmwareAttackScenario:
        if not trusted_package or not trusted_signature:
            raise ValueError("A signed baseline package is required.")
        return FirmwareAttackScenario(
            name="cloud_update_attack",
            version=version,
            package=trusted_package + b"\nTAMPERED",
            signature=trusted_signature,
            description="Cloud update package modified after trusted signing.",
        )

    def ecu_update_attack(self, version: str, package: bytes) -> FirmwareAttackScenario:
        if not package:
            raise ValueError("Firmware package cannot be empty.")
        return FirmwareAttackScenario(
            name="ecu_update_attack",
            version=version,
            package=package,
            signature="forged-signature",
            description="Forged local ECU update with no trusted manufacturer signature.",
        )
