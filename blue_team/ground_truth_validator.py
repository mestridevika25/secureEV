"""
ground_truth_validator.py

SecureEV Phase 7 - Ground Truth Validation.

Purpose:
    Compare network-reported telemetry with trusted references.

Trusted sources in the current testbed:
    - CARLA ground truth for physical motion/location (speed + GPS).
    - A trusted VehicleState snapshot for BMS SOC, because CARLA does not
      expose the simulated battery state used by SecureEV.

The validator is deliberately independent of MQTT transport and CARLA:
    callers provide the reported message and trusted references. This keeps
    CarlaBridge as the only module that communicates directly with CARLA.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Optional


@dataclass(frozen=True)
class GroundTruthFinding:
    """Result of validating one reported telemetry field."""

    detected: bool
    attack_type: str
    ecu: str
    field: str
    actual_value: Any
    reported_value: Any
    deviation: float | None
    tolerance: float | None
    severity: str
    reason: str

    @property
    def is_consistent(self) -> bool:
        return not self.detected


class GroundTruthValidator:
    """Validate selected ECU telemetry against trusted references."""

    def __init__(
        self,
        speed_tolerance_kmh: float = 5.0,
        gps_tolerance_m: float = 5.0,
        soc_tolerance_percent: float = 5.0,
    ) -> None:
        for name, value in (
            ("speed_tolerance_kmh", speed_tolerance_kmh),
            ("gps_tolerance_m", gps_tolerance_m),
            ("soc_tolerance_percent", soc_tolerance_percent),
        ):
            if value < 0:
                raise ValueError(f"{name} must be >= 0.")

        self.speed_tolerance_kmh = float(speed_tolerance_kmh)
        self.gps_tolerance_m = float(gps_tolerance_m)
        self.soc_tolerance_percent = float(soc_tolerance_percent)

        self.checked_count = 0
        self.detected_count = 0
        self.consistent_count = 0
        self.findings: list[GroundTruthFinding] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def validate_message(
        self,
        topic: str,
        message: dict[str, Any],
        *,
        carla_ground_truth: Optional[dict[str, Any]] = None,
        trusted_battery_soc: Optional[float] = None,
    ) -> GroundTruthFinding:
        """Validate a supported telemetry message.

        Supported comparisons:
            VCU speed_kmh       -> CARLA ground truth speed_kmh
            BMS battery_soc     -> trusted battery SOC snapshot
            TCU reported_gps    -> CARLA ground truth location
        """
        if not isinstance(message, dict):
            raise TypeError("message must be a dictionary.")

        self.checked_count += 1

        ecu = str(message.get("ecu", "")).upper()
        data = message.get("data")
        if not isinstance(data, dict):
            return self._record(
                GroundTruthFinding(
                    detected=True,
                    attack_type="invalid_telemetry",
                    ecu=ecu,
                    field="data",
                    actual_value=None,
                    reported_value=data,
                    deviation=None,
                    tolerance=None,
                    severity="MEDIUM",
                    reason="telemetry data is not an object",
                )
            )

        # --------------------------------------------------------------
        # VCU speed -> CARLA speed
        # --------------------------------------------------------------
        if ecu == "VCU" and "speed_kmh" in data:
            if carla_ground_truth is None:
                raise ValueError("carla_ground_truth is required for VCU speed validation.")

            actual = self._finite_float(carla_ground_truth.get("speed_kmh"))
            reported = self._finite_float(data.get("speed_kmh"))
            if actual is None or reported is None:
                return self._record(
                    GroundTruthFinding(
                        detected=True,
                        attack_type="invalid_speed_telemetry",
                        ecu=ecu,
                        field="speed_kmh",
                        actual_value=actual,
                        reported_value=reported,
                        deviation=None,
                        tolerance=self.speed_tolerance_kmh,
                        severity="HIGH",
                        reason="speed value is missing or non-finite",
                    )
                )

            deviation = abs(reported - actual)
            detected = deviation > self.speed_tolerance_kmh
            return self._record(
                GroundTruthFinding(
                    detected=detected,
                    attack_type="speed_spoofing" if detected else "none",
                    ecu=ecu,
                    field="speed_kmh",
                    actual_value=actual,
                    reported_value=reported,
                    deviation=deviation,
                    tolerance=self.speed_tolerance_kmh,
                    severity="HIGH" if detected else "INFO",
                    reason=(
                        "reported speed differs from CARLA ground truth"
                        if detected
                        else "reported speed is within CARLA tolerance"
                    ),
                )
            )

        # --------------------------------------------------------------
        # BMS SOC -> trusted digital-twin snapshot
        # --------------------------------------------------------------
        if ecu == "BMS" and "battery_soc" in data:
            if trusted_battery_soc is None:
                raise ValueError("trusted_battery_soc is required for BMS SOC validation.")

            actual = self._finite_float(trusted_battery_soc)
            reported = self._finite_float(data.get("battery_soc"))
            if actual is None or reported is None:
                return self._record(
                    GroundTruthFinding(
                        detected=True,
                        attack_type="invalid_battery_telemetry",
                        ecu=ecu,
                        field="battery_soc",
                        actual_value=actual,
                        reported_value=reported,
                        deviation=None,
                        tolerance=self.soc_tolerance_percent,
                        severity="HIGH",
                        reason="battery SOC is missing or non-finite",
                    )
                )

            deviation = abs(reported - actual)
            detected = deviation > self.soc_tolerance_percent
            return self._record(
                GroundTruthFinding(
                    detected=detected,
                    attack_type="battery_soc_spoofing" if detected else "none",
                    ecu=ecu,
                    field="battery_soc",
                    actual_value=actual,
                    reported_value=reported,
                    deviation=deviation,
                    tolerance=self.soc_tolerance_percent,
                    severity="HIGH" if detected else "INFO",
                    reason=(
                        "reported battery SOC differs from trusted digital-twin state"
                        if detected
                        else "reported battery SOC is within trusted tolerance"
                    ),
                )
            )

        # --------------------------------------------------------------
        # TCU GPS -> CARLA location
        # --------------------------------------------------------------
        if ecu == "TCU" and "reported_gps" in data:
            if carla_ground_truth is None:
                raise ValueError("carla_ground_truth is required for TCU GPS validation.")

            actual_location = carla_ground_truth.get("location")
            reported_location = data.get("reported_gps")
            if not self._valid_location(actual_location) or not self._valid_location(reported_location):
                return self._record(
                    GroundTruthFinding(
                        detected=True,
                        attack_type="invalid_gps_telemetry",
                        ecu=ecu,
                        field="reported_gps",
                        actual_value=actual_location,
                        reported_value=reported_location,
                        deviation=None,
                        tolerance=self.gps_tolerance_m,
                        severity="CRITICAL",
                        reason="GPS location is missing or malformed",
                    )
                )

            deviation = self._euclidean_distance_3d(
                actual_location,
                reported_location,
            )
            detected = deviation > self.gps_tolerance_m
            return self._record(
                GroundTruthFinding(
                    detected=detected,
                    attack_type="gps_spoofing" if detected else "none",
                    ecu=ecu,
                    field="reported_gps",
                    actual_value=dict(actual_location),
                    reported_value=dict(reported_location),
                    deviation=deviation,
                    tolerance=self.gps_tolerance_m,
                    severity="CRITICAL" if detected else "INFO",
                    reason=(
                        "reported GPS position differs from CARLA ground truth"
                        if detected
                        else "reported GPS position is within CARLA tolerance"
                    ),
                )
            )

        return self._record(
            GroundTruthFinding(
                detected=False,
                attack_type="unsupported_telemetry",
                ecu=ecu,
                field="unknown",
                actual_value=None,
                reported_value=None,
                deviation=None,
                tolerance=None,
                severity="INFO",
                reason="telemetry field has no Phase 7 ground-truth comparison",
            )
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _record(self, finding: GroundTruthFinding) -> GroundTruthFinding:
        self.findings.append(finding)
        if finding.detected:
            self.detected_count += 1
        else:
            self.consistent_count += 1
        return finding

    @staticmethod
    def _finite_float(value: Any) -> float | None:
        if isinstance(value, bool):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    @staticmethod
    def _valid_location(value: Any) -> bool:
        if not isinstance(value, dict):
            return False
        for key in ("x", "y", "z"):
            number = GroundTruthValidator._finite_float(value.get(key))
            if number is None:
                return False
        return True

    @staticmethod
    def _euclidean_distance_3d(a: dict[str, Any], b: dict[str, Any]) -> float:
        return math.sqrt(
            (float(a["x"]) - float(b["x"])) ** 2
            + (float(a["y"]) - float(b["y"])) ** 2
            + (float(a["z"]) - float(b["z"])) ** 2
        )
