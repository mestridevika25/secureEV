from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from blue_team.response_engine import ResponseAction, ResponseEngine


@dataclass(frozen=True)
class RuntimeResponseResult:
    finding_attack_type: str
    severity: str
    ecu: str
    detected: bool
    actions: tuple[ResponseAction, ...]


class RuntimeResponseCoordinator:
    """Connect validated Blue-Team findings to the live response engine."""

    def __init__(self, response_engine: ResponseEngine) -> None:
        if response_engine is None:
            raise ValueError("response_engine cannot be None.")
        self.response_engine = response_engine
        self.handled_findings = 0
        self.detected_findings = 0

    def handle_finding(self, finding: Any) -> RuntimeResponseResult:
        actions = tuple(self.response_engine.handle_finding(finding))
        detected = bool(getattr(finding, "detected", False))
        if detected:
            self.detected_findings += 1
        self.handled_findings += 1
        return RuntimeResponseResult(
            finding_attack_type=str(getattr(finding, "attack_type", "unknown")),
            severity=str(getattr(finding, "severity", "INFO")),
            ecu=str(getattr(finding, "ecu", "UNKNOWN")),
            detected=detected,
            actions=actions,
        )

    def status(self) -> dict[str, Any]:
        return {
            "handled_findings": self.handled_findings,
            "detected_findings": self.detected_findings,
            **self.response_engine.get_status(),
        }
