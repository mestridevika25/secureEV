"""SecureEV Phase 8B - live CARLA response integration test."""
from __future__ import annotations

from dataclasses import dataclass
import time

from blue_team.response_engine import ResponseEngine
from blue_team.runtime_response import RuntimeResponseCoordinator
from digital_twin.vehicle_state import VehicleState
from digital_twin.vcu import VCU
from simulation.carla_bridge import CarlaBridge


@dataclass(frozen=True)
class FindingStub:
    detected: bool
    attack_type: str
    ecu: str
    severity: str
    reason: str


def tick_for(bridge: CarlaBridge, seconds: float, interval: float = 0.05) -> float:
    end = time.time() + seconds
    last = bridge.get_ground_truth_state()
    while time.time() < end:
        last = bridge.get_ground_truth_state()
        time.sleep(interval)
    return float(last["speed_kmh"])


def main() -> int:
    print("= " * 35)
    print(" SecureEV - PHASE 8B RUNTIME RESPONSE INTEGRATION TEST")
    print("= " * 35)
    bridge = None
    try:
        print("\n[1] Connecting to CARLA...")
        bridge = CarlaBridge(host="localhost", port=2000, timeout=10.0)
        bridge.spawn_vehicle("vehicle.tesla.model3", spawn_index=0)
        bridge.set_autopilot(False)
        time.sleep(0.8)

        state = VehicleState()
        vcu = VCU(state, bridge)
        engine = ResponseEngine(vcu=vcu)
        coordinator = RuntimeResponseCoordinator(engine)

        print("[2] Establishing live vehicle motion...")
        vcu.apply_command(throttle=0.35, brake=0.0, steer=0.0)
        speed_before = tick_for(bridge, 2.0)
        if speed_before < 2.0:
            print(f"Live vehicle movement FAILED: {speed_before:.2f} km/h")
            return 1
        print(f"Vehicle speed before response: {speed_before:.2f} km/h")

        print("[3] Verifying HIGH finding does not emergency-brake...")
        high = coordinator.handle_finding(
            FindingStub(
                detected=True,
                attack_type="speed_spoofing",
                ecu="VCU",
                severity="HIGH",
                reason="reported speed differs from CARLA ground truth",
            )
        )
        if {a.action for a in high.actions} != {"isolate_ecu", "mark_untrusted"}:
            print("HIGH response policy FAILED")
            return 1
        if vcu.brake != 0.0:
            print("HIGH response unexpectedly braked vehicle.")
            return 1
        print("HIGH -> isolate + untrust, no emergency brake: PASSED")

        print("[4] Re-establishing motion for critical-response test...")
        vcu.apply_command(throttle=0.35, brake=0.0, steer=0.0)
        time.sleep(0.8)
        speed_before_critical = float(bridge.get_ground_truth_state()["speed_kmh"])
        if speed_before_critical < 2.0:
            print(f"Critical-response baseline movement FAILED: {speed_before_critical:.2f} km/h")
            return 1
        print(f"Critical-response baseline speed: {speed_before_critical:.2f} km/h")

        print("[5] Applying CRITICAL finding through runtime coordinator...")
        critical = coordinator.handle_finding(
            FindingStub(
                detected=True,
                attack_type="gps_spoofing",
                ecu="TCU",
                severity="CRITICAL",
                reason="reported GPS differs critically from CARLA ground truth",
            )
        )
        if {a.action for a in critical.actions} != {
            "isolate_ecu", "mark_untrusted", "emergency_brake"
        }:
            print("CRITICAL response action set FAILED")
            return 1
        if vcu.throttle != 0.0 or vcu.brake != 1.0 or vcu.steer != 0.0:
            print(
                "Emergency-brake control state FAILED: "
                f"throttle={vcu.throttle:.2f} brake={vcu.brake:.2f} steer={vcu.steer:.2f}"
            )
            return 1
        print("CRITICAL -> isolate + untrust + emergency brake: PASSED")

        print("[6] Verifying physical vehicle reaches safe state...")
        final_speed = tick_for(bridge, 2.0)
        print(f"Vehicle speed after emergency response: {final_speed:.2f} km/h")
        if final_speed > 2.0:
            print("Vehicle safe-state stop FAILED")
            return 1
        print("Physical CARLA safe-state response: PASSED")

        status = coordinator.status()
        if status["detected_findings"] != 2 or status["emergency_brake_count"] != 1:
            print("Response accounting FAILED")
            return 1
        print("[7] Runtime response accounting: PASSED")
        print(f"Handled findings : {status['handled_findings']}")
        print(f"Detected findings: {status['detected_findings']}")
        print(f"Emergency brakes : {status['emergency_brake_count']}")

        print("\n" + "=" * 70)
        print(" PHASE 8B RUNTIME RESPONSE INTEGRATION TEST PASSED")
        print("=" * 70)
        return 0
    finally:
        if bridge is not None:
            try:
                bridge.cleanup()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
