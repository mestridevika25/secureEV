"""
test_vcu_mqtt.py

SecureEV Phase 4C - live VCU telemetry over MQTT.

Pipeline under test:
    CARLA -> CarlaBridge -> VehicleState -> VCU -> MQTT -> Subscriber

No RGB camera is attached in this test. This keeps the MQTT integration test
independent of the rendering workload and lets us focus on the data path.
"""

from __future__ import annotations

import time
import uuid

from digital_twin.digital_twin_manager import DigitalTwinManager
from digital_twin.vcu import VCU
from digital_twin.vehicle_state import VehicleState
from network.ecu_telemetry_bridge import ECUTelemetryBridge
from network.mqtt_config import VCU_TELEMETRY
from network.publisher import MQTTPublisher
from network.subscriber import MQTTSubscriber
from simulation.carla_bridge import CarlaBridge


def main() -> int:
    print()
    print("=" * 60)
    print(" SecureEV - PHASE 4C LIVE VCU -> MQTT TEST")
    print("=" * 60)

    bridge: CarlaBridge | None = None
    publisher: MQTTPublisher | None = None
    subscriber: MQTTSubscriber | None = None

    received_messages: list[dict] = []

    def on_message(topic: str, payload: dict) -> None:
        if topic == VCU_TELEMETRY:
            received_messages.append(payload)

    try:
        # ----------------------------------------------------
        # 1. CARLA
        # ----------------------------------------------------
        print("\n[1] Connecting to CARLA...")
        bridge = CarlaBridge(host="localhost", port=2000, timeout=10.0)
        bridge.spawn_vehicle("vehicle.tesla.model3", spawn_index=0)
        print("CARLA vehicle ready. No camera attached.")

        # ----------------------------------------------------
        # 2. Digital Twin + VCU
        # ----------------------------------------------------
        print("[2] Creating VehicleState + VCU...")
        vehicle_state = VehicleState()
        vcu = VCU(
            vehicle_state=vehicle_state,
            carla_bridge=bridge,
        )

        manager = DigitalTwinManager(
            vehicle_state=vehicle_state,
            tick_rate_hz=10.0,
        )
        manager.register_ecu(vcu)

        # ----------------------------------------------------
        # 3. MQTT subscriber
        # ----------------------------------------------------
        print("[3] Connecting MQTT subscriber...")
        subscriber = MQTTSubscriber(
            client_id=f"secureev-vcu-sub-{uuid.uuid4().hex[:8]}",
            message_handler=on_message,
        )

        if not subscriber.connect():
            print("Subscriber connection FAILED.")
            return 1

        if not subscriber.subscribe(VCU_TELEMETRY):
            print("Subscriber subscription FAILED.")
            return 1

        # ----------------------------------------------------
        # 4. MQTT publisher
        # ----------------------------------------------------
        print("[4] Connecting MQTT publisher...")
        publisher = MQTTPublisher(
            client_id=f"secureev-vcu-pub-{uuid.uuid4().hex[:8]}"
        )

        if not publisher.connect():
            print("Publisher connection FAILED.")
            return 1

        telemetry_bridge = ECUTelemetryBridge(
            publisher=publisher,
        )

        # Let the network settle before the first message.
        time.sleep(0.5)

        # ----------------------------------------------------
        # 5. Drive + publish actual VCU telemetry
        # ----------------------------------------------------
        print("[5] Publishing LIVE VCU telemetry...")
        print(f"Topic: {VCU_TELEMETRY}")

        start = time.time()
        duration = 8.0
        last_print = -1

        while time.time() - start < duration:
            elapsed = time.time() - start

            # Controlled test drive:
            # 0-4 s: accelerate
            # 4-6 s: coast
            # 6-8 s: brake
            if elapsed < 4.0:
                vcu.apply_command(
                    throttle=0.25,
                    brake=0.0,
                    steer=0.0,
                )
                phase = "ACCELERATING"
            elif elapsed < 6.0:
                vcu.apply_command(
                    throttle=0.0,
                    brake=0.0,
                    steer=0.0,
                )
                phase = "COASTING"
            else:
                vcu.apply_command(
                    throttle=0.0,
                    brake=0.40,
                    steer=0.0,
                )
                phase = "BRAKING"

            all_telemetry = manager.tick()
            vcu_telemetry = all_telemetry["VCU"]

            published = telemetry_bridge.publish_vcu(vcu_telemetry)

            # Print roughly once per second so the test remains readable.
            second = int(elapsed)
            if second != last_print:
                last_print = second
                print(
                    f"  t={elapsed:4.1f}s | {phase:11s} | "
                    f"speed={vcu_telemetry['speed_kmh']:6.2f} km/h | "
                    f"acc={vcu_telemetry['acceleration_mps2']:6.3f} m/s² | "
                    f"throttle={vcu_telemetry['throttle']:.2f} | "
                    f"brake={vcu_telemetry['brake']:.2f} | "
                    f"published={published}"
                )

            time.sleep(0.1)

        # Ensure the vehicle isn't left under throttle after the test.
        vcu.emergency_brake()
        manager.tick()

        # ----------------------------------------------------
        # 6. Validate received network data
        # ----------------------------------------------------
        print("\n[6] Validating received MQTT telemetry...")

        # Give the subscriber loop a brief chance to receive the last packet.
        time.sleep(0.5)

        if not received_messages:
            print("No VCU telemetry messages were received.")
            return 1

        first = received_messages[0]
        last = received_messages[-1]

        checks = [
            first.get("protocol_version") == 1,
            first.get("vehicle_id") == "SEV-001",
            first.get("ecu") == "VCU",
            first.get("message_type") == "telemetry",
            isinstance(first.get("sequence"), int),
            isinstance(first.get("data"), dict),
            "speed_kmh" in first.get("data", {}),
            "acceleration_mps2" in first.get("data", {}),
            "throttle" in first.get("data", {}),
            "brake" in first.get("data", {}),
        ]

        if not all(checks):
            print("Message validation FAILED.")
            print(f"First message: {first}")
            return 1

        sequences = [msg.get("sequence") for msg in received_messages]
        monotonically_increasing = sequences == sorted(sequences)

        if not monotonically_increasing:
            print("Sequence validation FAILED.")
            print(f"Sequences: {sequences}")
            return 1

        first_speed = float(first["data"]["speed_kmh"])
        last_speed = float(last["data"]["speed_kmh"])

        print(f"Messages received : {len(received_messages)}")
        print(f"First sequence    : {first['sequence']}")
        print(f"Last sequence     : {last['sequence']}")
        print(f"First speed       : {first_speed:.2f} km/h")
        print(f"Last speed        : {last_speed:.2f} km/h")
        print(f"Sequence order    : {'PASSED' if monotonically_increasing else 'FAILED'}")
        print("Message validation: PASSED")

        print("\n" + "=" * 60)
        print(" PHASE 4C LIVE VCU -> MQTT TEST PASSED")
        print("=" * 60)
        return 0

    except Exception as exc:
        print(f"\nPHASE 4C TEST ERROR: {exc}")
        return 1

    finally:
        print("\n[7] Cleaning up...")

        if publisher is not None:
            publisher.disconnect()

        if subscriber is not None:
            subscriber.disconnect()

        if bridge is not None:
            bridge.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
