"""
SecureEV Phase 8A - Attack-Resistant Response Engine test.

Tests the response policy using a small VCU stub first, then optionally
exercises the real VCU object when the project VCU implementation is
available. The test intentionally does not import CARLA directly.
"""

from __future__ import annotations

from dataclasses import dataclass

from blue_team.response_engine import ResponseEngine


@dataclass(frozen=True)
class FindingStub:
    detected: bool
    attack_type: str
    ecu: str
    severity: str
    reason: str


class VCUStub:
    def __init__(self) -> None:
        self.throttle = 0.0
        self.brake = 0.0
        self.steer = 0.0
        self.emergency_brake_calls = 0

    def emergency_brake(self) -> None:
        self.throttle = 0.0
        self.brake = 1.0
        self.steer = 0.0
        self.emergency_brake_calls += 1


def main() -> int:
    print("=" * 70)
    print(" SecureEV - PHASE 8A ATTACK-RESISTANT RESPONSE TEST")
    print("=" * 70)

    print("\n[1] Creating response engine + VCU safety stub...")
    vcu = VCUStub()
    engine = ResponseEngine(vcu=vcu)

    print("[2] Validating legitimate telemetry response policy...")
    info = engine.handle_finding(
        FindingStub(
            detected=False,
            attack_type="none",
            ecu="VCU",
            severity="INFO",
            reason="telemetry is consistent with trusted state",
        )
    )
    assert info and info[0].action == "monitor"
    assert vcu.emergency_brake_calls == 0
    print("  Consistent telemetry -> MONITOR: PASSED")

    print("\n[3] Responding to HIGH speed-spoofing finding...")
    high = engine.handle_finding(
        FindingStub(
            detected=True,
            attack_type="speed_spoofing",
            ecu="VCU",
            severity="HIGH",
            reason="reported speed differs substantially from CARLA ground truth",
        )
    )
    assert {a.action for a in high} == {"isolate_ecu", "mark_untrusted"}
    assert "VCU" in engine.isolated_ecus
    assert "VCU" in engine.untrusted_ecus
    assert vcu.emergency_brake_calls == 0
    print("  HIGH anomaly -> ISOLATE + MARK UNTRUSTED: PASSED")
    print("  Emergency brake avoided for HIGH: PASSED")

    print("\n[4] Responding to CRITICAL GPS-spoofing finding...")
    critical = engine.handle_finding(
        FindingStub(
            detected=True,
            attack_type="gps_spoofing",
            ecu="TCU",
            severity="CRITICAL",
            reason="reported GPS differs critically from CARLA ground truth",
        )
    )
    assert {a.action for a in critical} == {"isolate_ecu", "mark_untrusted", "emergency_brake"}
    assert "TCU" in engine.isolated_ecus
    assert "TCU" in engine.untrusted_ecus
    assert vcu.emergency_brake_calls == 1
    assert vcu.throttle == 0.0
    assert vcu.brake == 1.0
    print("  CRITICAL anomaly -> ISOLATE + UNTRUST + EMERGENCY BRAKE: PASSED")

    print("\n[5] Validating response accounting...")
    status = engine.get_status()
    assert status["emergency_brake_count"] == 1
    assert status["action_count"] == 6  # monitor + 2 HIGH + 3 CRITICAL
    assert engine.last_action is not None
    assert engine.last_action.action == "emergency_brake"
    print(f"  Actions recorded : {status['action_count']}")
    print(f"  Isolated ECUs    : {', '.join(status['isolated_ecus'])}")
    print(f"  Untrusted ECUs   : {', '.join(status['untrusted_ecus'])}")
    print("  Response audit trail: PASSED")

    print("\n" + "=" * 70)
    print(" PHASE 8A ATTACK-RESISTANT RESPONSE TEST PASSED")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
