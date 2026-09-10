"""
test_phase7_ground_truth_validation.py

SecureEV Phase 7 - Ground Truth Validation test.

Creates a trusted CARLA reference, injects the Phase 6B false telemetry, and
proves that the Blue Team GroundTruthValidator detects the mismatches while a
legitimate telemetry sample remains consistent.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from blue_team.ground_truth_validator import GroundTruthValidator
from digital_twin.vehicle_state import VehicleState
from network.message_schema import create_message
from network.mqtt_config import BMS_TELEMETRY, TCU_TELEMETRY, VCU_TELEMETRY
from network.publisher import MQTTPublisher
from network.subscriber import MQTTSubscriber
from red_team.data_spoofing import DataSpoofingAttacker, TelemetrySpoofScenario
from simulation.carla_bridge import CarlaBridge


TELEMETRY_TOPICS = {VCU_TELEMETRY, BMS_TELEMETRY, TCU_TELEMETRY}


def wait_for_ids(
    received: dict[str, dict[str, Any]],
    message_ids: set[str],
    timeout: float = 4.0,
) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if message_ids.issubset(received.keys()):
            return True
        time.sleep(0.02)
    return message_ids.issubset(received.keys())


def build_legitimate_messages(
    ground_truth: dict[str, Any],
    trusted_soc: float,
) -> list[tuple[str, dict[str, Any]]]:
    """Create telemetry that should NOT trigger Phase 7."""
    messages = [
        (
            VCU_TELEMETRY,
            create_message(
                ecu="VCU",
                message_type="telemetry",
                data={
                    "speed_kmh": float(ground_truth["speed_kmh"]),
                    "acceleration_mps2": 0.0,
                    "throttle": 0.0,
                    "brake": 0.0,
                    "steer": 0.0,
                },
                sequence=50,
                vehicle_id="SEV-001",
            ),
        ),
        (
            BMS_TELEMETRY,
            create_message(
                ecu="BMS",
                message_type="telemetry",
                data={
                    "battery_soc": trusted_soc,
                    "battery_temp": 25.0,
                    "battery_capacity_kwh": 75.0,
                    "energy_consumed_kwh": 0.0,
                    "energy_charged_kwh": 0.0,
                },
                sequence=50,
                vehicle_id="SEV-001",
            ),
        ),
        (
            TCU_TELEMETRY,
            create_message(
                ecu="TCU",
                message_type="telemetry",
                data={
                    "reported_gps": {
                        "x": float(ground_truth["location"]["x"]),
                        "y": float(ground_truth["location"]["y"]),
                        "z": float(ground_truth["location"]["z"]),
                    },
                    "gps_source": "CARLA",
                },
                sequence=50,
                vehicle_id="SEV-001",
            ),
        ),
    ]
    return messages


def main() -> int:
    print()
    print("=" * 70)
    print(" SecureEV - PHASE 7 GROUND TRUTH VALIDATION TEST")
    print("=" * 70)

    carla_bridge: CarlaBridge | None = None
    publisher: MQTTPublisher | None = None
    subscriber: MQTTSubscriber | None = None

    received: dict[str, dict[str, Any]] = {}

    def on_message(topic: str, payload: dict[str, Any]) -> None:
        if topic in TELEMETRY_TOPICS:
            message_id = payload.get("message_id")
            if isinstance(message_id, str):
                received[message_id] = payload

    try:
        # ------------------------------------------------------------
        # 1. Trusted references
        # ------------------------------------------------------------
        print("\n[1] Establishing trusted references...")
        carla_bridge = CarlaBridge(host="localhost", port=2000, timeout=10.0)
        carla_bridge.spawn_vehicle("vehicle.tesla.model3", spawn_index=0)
        carla_bridge.set_autopilot(False)

        time.sleep(1.0)
        ground_truth = carla_bridge.get_ground_truth_state()
        for _ in range(10):
            if abs(float(ground_truth["speed_kmh"])) <= 0.25:
                break
            time.sleep(0.1)
            ground_truth = carla_bridge.get_ground_truth_state()

        # CARLA does not model SecureEV's battery state, so use a trusted
        # VehicleState snapshot for the BMS comparison.
        trusted_state = VehicleState(battery_soc=80.0)
        trusted_soc = float(trusted_state.battery_soc)

        print(
            "CARLA trusted speed: "
            f"{ground_truth['speed_kmh']:.2f} km/h"
        )
        print(
            "CARLA trusted location: "
            f"{ground_truth['location']}"
        )
        print(f"Trusted digital-twin SOC: {trusted_soc:.2f} %")

        validator = GroundTruthValidator(
            speed_tolerance_kmh=5.0,
            gps_tolerance_m=5.0,
            soc_tolerance_percent=5.0,
        )

        # ------------------------------------------------------------
        # 2. MQTT observer + publisher
        # ------------------------------------------------------------
        print("[2] Connecting MQTT telemetry observer...")
        subscriber = MQTTSubscriber(
            client_id=f"secureev-phase7-observer-{uuid.uuid4().hex[:8]}",
            message_handler=on_message,
        )
        if not subscriber.connect() or not subscriber.subscribe("secureev/+/telemetry"):
            print("MQTT observer setup FAILED.")
            return 1

        print("[3] Connecting Red Team MQTT publisher...")
        publisher = MQTTPublisher(
            client_id=f"secureev-phase7-publisher-{uuid.uuid4().hex[:8]}"
        )
        if not publisher.connect():
            print("MQTT publisher connection FAILED.")
            return 1

        attacker = DataSpoofingAttacker(publisher=publisher)
        time.sleep(0.5)

        # ------------------------------------------------------------
        # 3. Negative control: legitimate telemetry should be consistent
        # ------------------------------------------------------------
        print("\n[4] Validating legitimate telemetry baseline...")
        legitimate = build_legitimate_messages(ground_truth, trusted_soc)
        legitimate_ids: set[str] = set()
        for topic, message in legitimate:
            legitimate_ids.add(message["message_id"])
            if not publisher.publish(topic, message, qos=1):
                print("Failed to publish legitimate baseline telemetry.")
                return 1

        if not wait_for_ids(received, legitimate_ids):
            print("Legitimate telemetry was not observed on MQTT.")
            return 1

        legitimate_findings: list[Any] = []
        for topic, message in legitimate:
            finding = validator.validate_message(
                topic,
                received[message["message_id"]],
                carla_ground_truth=ground_truth,
                trusted_battery_soc=trusted_soc,
            )
            legitimate_findings.append(finding)
            print(
                f"  {finding.ecu} {finding.field}: "
                f"{'CONSISTENT' if not finding.detected else 'UNEXPECTED DETECTION'}"
            )

        baseline_passed = all(not finding.detected for finding in legitimate_findings)

        # ------------------------------------------------------------
        # 4. Phase 6B attack telemetry
        # ------------------------------------------------------------
        print("\n[5] Replaying controlled Phase 6B telemetry attacks...")
        scenarios: list[TelemetrySpoofScenario] = [
            attacker.speed_spoofing(sequence=1, spoofed_speed_kmh=180.0),
            attacker.battery_soc_spoofing(sequence=1, spoofed_soc=99.0),
            attacker.gps_spoofing(
                sequence=1,
                spoofed_location={"x": 99999.0, "y": -99999.0, "z": 10.0},
            ),
        ]

        for index, scenario in enumerate(scenarios, start=1):
            print(f"  [{index}] {scenario.name}...")
            if not attacker.publish_attack(scenario):
                print(f"Attack publish FAILED: {scenario.name}")
                return 1

        attack_ids = {scenario.message["message_id"] for scenario in scenarios}
        if not wait_for_ids(received, attack_ids):
            print("Not all spoofed telemetry messages were observed.")
            return 1

        # ------------------------------------------------------------
        # 5. Ground-truth comparison
        # ------------------------------------------------------------
        print("\n[6] Comparing reported telemetry against trusted state...")
        findings: list[Any] = []
        for scenario in scenarios:
            finding = validator.validate_message(
                scenario.topic,
                received[scenario.message["message_id"]],
                carla_ground_truth=ground_truth,
                trusted_battery_soc=trusted_soc,
            )
            findings.append(finding)

            deviation_text = (
                "n/a" if finding.deviation is None else f"{finding.deviation:.2f}"
            )
            print(
                f"  {finding.attack_type}: "
                f"actual={finding.actual_value} | "
                f"reported={finding.reported_value} | "
                f"deviation={deviation_text} | "
                f"severity={finding.severity} | "
                f"{'ATTACK DETECTED' if finding.detected else 'NO ATTACK'}"
            )

        speed_detected = any(f.attack_type == "speed_spoofing" and f.detected for f in findings)
        soc_detected = any(f.attack_type == "battery_soc_spoofing" and f.detected for f in findings)
        gps_detected = any(f.attack_type == "gps_spoofing" and f.detected for f in findings)

        detection_passed = speed_detected and soc_detected and gps_detected

        # ------------------------------------------------------------
        # 6. Verify physical CARLA state remained trusted
        # ------------------------------------------------------------
        print("\n[7] Confirming CARLA state was not altered by telemetry spoofing...")
        ground_after = carla_bridge.get_ground_truth_state()
        speed_delta = abs(
            float(ground_after["speed_kmh"]) - float(ground_truth["speed_kmh"])
        )
        position_delta = math_distance(
            ground_truth["location"],
            ground_after["location"],
        )
        physical_state_safe = speed_delta <= 1.0 and position_delta <= 0.5

        print(f"CARLA speed after attack: {ground_after['speed_kmh']:.2f} km/h")
        print(f"CARLA position after attack: {ground_after['location']}")
        print(f"Physical speed delta: {speed_delta:.2f} km/h")
        print(f"Physical position delta: {position_delta:.2f} m")

        # ------------------------------------------------------------
        # 7. Final validation
        # ------------------------------------------------------------
        print("\n[8] Validating Phase 7 behavior...")
        print(f"Legitimate baseline consistency: {'PASSED' if baseline_passed else 'FAILED'}")
        print(f"Speed spoofing detection         : {'PASSED' if speed_detected else 'FAILED'}")
        print(f"Battery SOC spoofing detection   : {'PASSED' if soc_detected else 'FAILED'}")
        print(f"GPS spoofing detection           : {'PASSED' if gps_detected else 'FAILED'}")
        print(f"Ground-truth integrity detection : {'PASSED' if detection_passed else 'FAILED'}")
        print(f"CARLA physical state protected   : {'PASSED' if physical_state_safe else 'FAILED'}")
        print(f"Ground-truth checks performed    : {validator.checked_count}")
        print(f"Anomalies detected               : {validator.detected_count}")
        print(f"Consistent samples               : {validator.consistent_count}")

        all_ok = (
            baseline_passed
            and detection_passed
            and physical_state_safe
        )

        print("\n" + "=" * 70)
        if all_ok:
            print(" PHASE 7 GROUND TRUTH VALIDATION TEST PASSED")
        else:
            print(" PHASE 7 GROUND TRUTH VALIDATION TEST FAILED")
        print("=" * 70)

        print("\nDetection summary:")
        for finding in findings:
            print(
                f"  {finding.attack_type}: "
                f"detected={finding.detected} | severity={finding.severity}"
            )

        return 0 if all_ok else 1

    except Exception as exc:
        print(f"\nPHASE 7 TEST ERROR: {exc}")
        return 1

    finally:
        print("\n[9] Cleaning up...")
        if publisher is not None:
            publisher.disconnect()
        if subscriber is not None:
            subscriber.disconnect()
        if carla_bridge is not None:
            carla_bridge.cleanup()


def math_distance(a: dict[str, Any], b: dict[str, Any]) -> float:
    return (
        (float(a["x"]) - float(b["x"])) ** 2
        + (float(a["y"]) - float(b["y"])) ** 2
        + (float(a["z"]) - float(b["z"])) ** 2
    ) ** 0.5


if __name__ == "__main__":
    raise SystemExit(main())
