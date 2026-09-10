"""
test_phase6b_data_spoofing.py

SecureEV Phase 6B - Red Team telemetry/data spoofing test.

Purpose:
    Prove that a Red Team publisher can inject false telemetry onto the MQTT
    virtual vehicle network while CARLA's trusted physical state remains
    unchanged.

This is intentionally different from Phase 6A.  Phase 6A attacks the VCU
command path and should be blocked by the Phase 5 Security Gateway.  Phase 6B
creates false telemetry, which is NOT yet protected by that gateway.  The false
telemetry becomes the attack condition that Phase 7 will detect by comparing
MQTT-reported values against CARLA ground truth.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from network.mqtt_config import (
    BMS_TELEMETRY,
    TCU_TELEMETRY,
    VCU_TELEMETRY,
)
from network.publisher import MQTTPublisher
from network.subscriber import MQTTSubscriber
from red_team.data_spoofing import DataSpoofingAttacker
from red_team.data_spoofing import TelemetrySpoofScenario
from simulation.carla_bridge import CarlaBridge


TELEMETRY_TOPICS = {
    VCU_TELEMETRY,
    BMS_TELEMETRY,
    TCU_TELEMETRY,
}


def wait_for_messages(
    received: dict[str, dict[str, Any]],
    message_ids: set[str],
    timeout: float = 3.0,
) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if message_ids.issubset(received.keys()):
            return True
        time.sleep(0.02)
    return message_ids.issubset(received.keys())


def locations_equal(
    a: dict[str, float],
    b: dict[str, float],
    tolerance_xy: float = 0.5,
    tolerance_z: float = 1.0,
) -> bool:
    """Compare CARLA positions while allowing normal physics/spawn settling."""
    return (
        abs(float(a["x"]) - float(b["x"])) <= tolerance_xy
        and abs(float(a["y"]) - float(b["y"])) <= tolerance_xy
        and abs(float(a["z"]) - float(b["z"])) <= tolerance_z
    )


def validate_attack_delivery(
    scenario: TelemetrySpoofScenario,
    received: dict[str, dict[str, Any]],
) -> bool:
    message = received.get(scenario.message["message_id"])
    if message is None:
        return False

    if message.get("protocol_version") != 1:
        return False
    if message.get("vehicle_id") != "SEV-001":
        return False
    if str(message.get("ecu", "")).upper() != scenario.ecu:
        return False
    if message.get("message_type") != "telemetry":
        return False
    if not isinstance(message.get("message_id"), str):
        return False
    if not isinstance(message.get("sequence"), int):
        return False
    if not isinstance(message.get("data"), dict):
        return False

    data = message["data"]
    actual = data.get(scenario.expected_field)

    if scenario.expected_field == "reported_gps":
        return isinstance(actual, dict) and actual == scenario.expected_value

    return actual == scenario.expected_value


def main() -> int:
    print()
    print("=" * 70)
    print(" SecureEV - PHASE 6B RED TEAM TELEMETRY-SPOOFING TEST")
    print("=" * 70)

    carla_bridge: CarlaBridge | None = None
    publisher: MQTTPublisher | None = None
    subscriber: MQTTSubscriber | None = None

    received: dict[str, dict[str, Any]] = {}

    def on_message(topic: str, payload: dict[str, Any]) -> None:
        if topic not in TELEMETRY_TOPICS:
            return
        message_id = payload.get("message_id")
        if isinstance(message_id, str):
            received[message_id] = payload

    try:
        # ------------------------------------------------------------
        # 1. CARLA ground truth reference
        # ------------------------------------------------------------
        print("\n[1] Connecting to CARLA...")
        carla_bridge = CarlaBridge(
            host="localhost",
            port=2000,
            timeout=10.0,
        )
        carla_bridge.spawn_vehicle(
            blueprint_id="vehicle.tesla.model3",
            spawn_index=0,
        )
        carla_bridge.set_autopilot(False)

        # Let the spawned vehicle settle before taking the trusted baseline.
        # This avoids confusing normal CARLA spawn/physics settling with a
        # telemetry attack.
        time.sleep(1.0)
        ground_before = carla_bridge.get_ground_truth_state()
        for _ in range(10):
            time.sleep(0.1)
            ground_before = carla_bridge.get_ground_truth_state()
            if abs(float(ground_before["speed_kmh"])) <= 0.25:
                break
        print("CARLA vehicle ready. No camera attached.")
        print(
            "Trusted ground truth before attacks: "
            f"speed={ground_before['speed_kmh']:.2f} km/h | "
            f"location={ground_before['location']}"
        )

        # ------------------------------------------------------------
        # 2. MQTT observer
        # ------------------------------------------------------------
        print("[2] Connecting MQTT telemetry observer...")
        subscriber = MQTTSubscriber(
            client_id=f"secureev-phase6b-observer-{uuid.uuid4().hex[:8]}",
            message_handler=on_message,
        )

        if not subscriber.connect():
            print("Telemetry observer connection FAILED.")
            return 1

        if not subscriber.subscribe("secureev/+/telemetry"):
            print("Telemetry wildcard subscription FAILED.")
            return 1

        # ------------------------------------------------------------
        # 3. Red Team publisher
        # ------------------------------------------------------------
        print("[3] Connecting Red Team MQTT publisher...")
        publisher = MQTTPublisher(
            client_id=f"secureev-redteam-telemetry-{uuid.uuid4().hex[:8]}"
        )

        if not publisher.connect():
            print("Red Team publisher connection FAILED.")
            return 1

        attacker = DataSpoofingAttacker(publisher=publisher)
        time.sleep(0.5)

        # ------------------------------------------------------------
        # 4. Create controlled spoofing scenarios
        # ------------------------------------------------------------
        print("\n[4] Creating controlled telemetry-spoofing attacks...")

        scenarios = [
            attacker.speed_spoofing(sequence=1, spoofed_speed_kmh=180.0),
            attacker.battery_soc_spoofing(sequence=1, spoofed_soc=99.0),
            attacker.gps_spoofing(
                sequence=1,
                spoofed_location={
                    "x": 99999.0,
                    "y": -99999.0,
                    "z": 10.0,
                },
            ),
        ]

        for index, scenario in enumerate(scenarios, start=1):
            print(f"  [{index}] {scenario.name}...")
            print(f"      {scenario.description}")
            if not attacker.publish_attack(scenario):
                print(f"Attack publish FAILED: {scenario.name}")
                return 1

        message_ids = {scenario.message["message_id"] for scenario in scenarios}

        # ------------------------------------------------------------
        # 5. Confirm spoofed data reached MQTT observer
        # ------------------------------------------------------------
        print("\n[5] Validating spoofed telemetry delivery...")
        delivered = wait_for_messages(received, message_ids)

        if not delivered:
            print("Not all spoofed telemetry messages were received.")
            print(f"Received message IDs: {list(received.keys())}")
            return 1

        delivery_results: list[bool] = []
        for scenario in scenarios:
            passed = validate_attack_delivery(scenario, received)
            delivery_results.append(passed)
            observed = received.get(scenario.message["message_id"], {})
            print(
                f"  {scenario.name}: "
                f"published=True | delivered={'YES' if passed else 'NO'}"
            )
            if not passed:
                print(f"      Observed message: {observed}")

        # ------------------------------------------------------------
        # 6. Confirm CARLA physical state was NOT modified by telemetry
        # ------------------------------------------------------------
        print("\n[6] Re-checking trusted CARLA state...")
        ground_after = carla_bridge.get_ground_truth_state()

        # Telemetry-only MQTT injection must not alter the physical CARLA
        # state. Small motion/position differences are tolerated because
        # CARLA physics can settle the vehicle by a fraction of a second.
        speed_delta = abs(
            float(ground_after["speed_kmh"]) - float(ground_before["speed_kmh"])
        )
        position_unchanged = locations_equal(
            ground_after["location"],
            ground_before["location"],
            tolerance_xy=0.5,
            tolerance_z=1.0,
        )
        ground_truth_unchanged = speed_delta <= 1.0 and position_unchanged

        print(
            "Trusted ground truth after attacks:  "
            f"speed={ground_after['speed_kmh']:.2f} km/h | "
            f"location={ground_after['location']}"
        )

        # ------------------------------------------------------------
        # 7. Security interpretation / phase result
        # ------------------------------------------------------------
        print("\n[7] Validating Phase 6B Red Team behavior...")
        print(f"Telemetry attacks launched : {len(scenarios)}")
        print(f"Spoofed messages delivered : {sum(delivery_results)}/{len(scenarios)}")
        print(
            "MQTT false-data injection : "
            f"{'PASSED' if all(delivery_results) else 'FAILED'}"
        )
        print(
            "CARLA physical state unchanged: "
            f"{'PASSED' if ground_truth_unchanged else 'FAILED'}"
            f" | speed_delta={speed_delta:.2f} km/h"
        )
        print("Phase 7 ground-truth detection required: YES")

        all_ok = all(delivery_results) and ground_truth_unchanged

        print("\n" + "=" * 70)
        if all_ok:
            print(" PHASE 6B RED TEAM TELEMETRY-SPOOFING TEST PASSED")
        else:
            print(" PHASE 6B RED TEAM TELEMETRY-SPOOFING TEST FAILED")
        print("=" * 70)

        print("\nAttack summary:")
        for scenario in scenarios:
            print(
                f"  {scenario.name}: "
                f"topic={scenario.topic} | "
                f"field={scenario.expected_field} | "
                f"spoofed={scenario.expected_value}"
            )

        return 0 if all_ok else 1

    except Exception as exc:
        print(f"\nPHASE 6B TEST ERROR: {exc}")
        return 1

    finally:
        print("\n[8] Cleaning up...")

        if publisher is not None:
            publisher.disconnect()

        if subscriber is not None:
            subscriber.disconnect()

        if carla_bridge is not None:
            carla_bridge.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
