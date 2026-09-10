"""
test_multi_ecu_mqtt.py

SecureEV Phase 4D - live telemetry from the five core ECUs over MQTT.

Pipeline under test:
    CARLA -> Digital Twin -> VCU/BMS/BCM/MCU/TCU -> MQTT -> Subscriber

No RGB camera is attached.  The purpose of this test is to verify the
connected-EV telemetry bus independently of CARLA rendering.
"""

from __future__ import annotations

import time
import uuid

from digital_twin.bcm import BCM
from digital_twin.bms import BMS
from digital_twin.digital_twin_manager import DigitalTwinManager
from digital_twin.mcu import MCU
from digital_twin.tcu import TCU
from digital_twin.vcu import VCU
from digital_twin.vehicle_state import VehicleState
from network.ecu_telemetry_bridge import ECUTelemetryBridge
from network.mqtt_config import (
    BCM_TELEMETRY,
    BMS_TELEMETRY,
    MCU_TELEMETRY,
    TCU_TELEMETRY,
    VCU_TELEMETRY,
)
from network.mqtt_config import VEHICLE_ID
from network.publisher import MQTTPublisher
from network.subscriber import MQTTSubscriber
from simulation.carla_bridge import CarlaBridge


ECU_TOPICS = {
    "VCU": VCU_TELEMETRY,
    "BMS": BMS_TELEMETRY,
    "BCM": BCM_TELEMETRY,
    "MCU": MCU_TELEMETRY,
    "TCU": TCU_TELEMETRY,
}

REQUIRED_FIELDS = {
    "VCU": {
        "speed_kmh",
        "acceleration_mps2",
        "throttle",
        "brake",
        "steer",
    },
    "BMS": {
        "battery_soc",
        "battery_temp",
        "battery_capacity_kwh",
        "energy_consumed_kwh",
    },
    "BCM": {
        "doors_locked",
        "doors_open",
    },
    "MCU": {
        "motor_rpm",
        "motor_temp",
    },
    "TCU": {
        "reported_gps",
        "gps_source",
    },
}


def main() -> int:
    print()
    print("=" * 64)
    print(" SecureEV - PHASE 4D MULTI-ECU MQTT TEST")
    print("=" * 64)

    carla_bridge: CarlaBridge | None = None
    publisher: MQTTPublisher | None = None
    subscriber: MQTTSubscriber | None = None

    received: dict[str, list[dict]] = {
        ecu: [] for ecu in ECU_TOPICS
    }

    def on_message(topic: str, payload: dict) -> None:
        for ecu, expected_topic in ECU_TOPICS.items():
            if topic == expected_topic:
                received[ecu].append(payload)
                return

    try:
        # ----------------------------------------------------
        # 1. CARLA
        # ----------------------------------------------------
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
        print("CARLA vehicle ready. No camera attached.")

        # ----------------------------------------------------
        # 2. Digital Twin + five core ECUs
        # ----------------------------------------------------
        print("[2] Creating five core ECUs...")

        vehicle_state = VehicleState()

        vcu = VCU(
            vehicle_state=vehicle_state,
            carla_bridge=carla_bridge,
        )
        bms = BMS(
            vehicle_state=vehicle_state,
            vcu=vcu,
        )
        bcm = BCM(
            vehicle_state=vehicle_state,
        )
        mcu = MCU(
            vehicle_state=vehicle_state,
            vcu=vcu,
        )
        tcu = TCU(
            vehicle_state=vehicle_state,
            carla_bridge=carla_bridge,
        )

        manager = DigitalTwinManager(
            vehicle_state=vehicle_state,
            tick_rate_hz=10.0,
        )

        for ecu in (vcu, bms, bcm, mcu, tcu):
            manager.register_ecu(ecu)

        print("Registered ECUs:")
        for ecu_id in manager.ecus:
            print(f"  - {ecu_id}: ONLINE")

        # ----------------------------------------------------
        # 3. MQTT subscriber
        # ----------------------------------------------------
        print("\n[3] Connecting MQTT subscriber...")
        subscriber = MQTTSubscriber(
            client_id=f"secureev-multi-sub-{uuid.uuid4().hex[:8]}",
            message_handler=on_message,
            verbose=False,
        )

        if not subscriber.connect():
            print("Subscriber connection FAILED.")
            return 1

        for topic in ECU_TOPICS.values():
            if not subscriber.subscribe(topic):
                print(f"Subscription FAILED: {topic}")
                return 1

        # ----------------------------------------------------
        # 4. MQTT publisher
        # ----------------------------------------------------
        print("[4] Connecting MQTT publisher...")
        publisher = MQTTPublisher(
            client_id=f"secureev-multi-pub-{uuid.uuid4().hex[:8]}"
        )

        if not publisher.connect():
            print("Publisher connection FAILED.")
            return 1

        telemetry_bridge = ECUTelemetryBridge(
            publisher=publisher,
            vehicle_id=VEHICLE_ID,
        )

        time.sleep(0.5)

        # ----------------------------------------------------
        # 5. Live multi-ECU telemetry
        # ----------------------------------------------------
        print("\n[5] Publishing live telemetry from five core ECUs...")
        print("      VCU | BMS | BCM | MCU | TCU")

        start = time.time()
        duration = 8.0
        last_printed_second = -1

        while time.time() - start < duration:
            elapsed = time.time() - start

            # Controlled motion profile:
            # 0-4 s -> accelerate
            # 4-6 s -> coast
            # 6-8 s -> brake
            if elapsed < 4.0:
                vcu.apply_command(
                    throttle=0.20,
                    brake=0.0,
                    steer=0.05,
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
                    brake=0.35,
                    steer=0.0,
                )
                phase = "BRAKING"

            all_telemetry = manager.tick()

            published_count = 0

            for ecu_id, topic in ECU_TOPICS.items():
                telemetry = all_telemetry[ecu_id]

                if telemetry_bridge.publish_telemetry(
                    ecu_id=ecu_id,
                    topic=topic,
                    telemetry=telemetry,
                ):
                    published_count += 1

            current_second = int(elapsed)
            if current_second != last_printed_second:
                last_printed_second = current_second

                print(
                    f"  t={elapsed:4.1f}s | {phase:11s} | "
                    f"speed={all_telemetry['VCU']['speed_kmh']:6.2f} km/h | "
                    f"SOC={all_telemetry['BMS']['battery_soc']:5.2f}% | "
                    f"RPM={all_telemetry['MCU']['motor_rpm']:7.1f} | "
                    f"ECUs published={published_count}/5"
                )

            time.sleep(0.1)

        vcu.emergency_brake()
        manager.tick()

        # ----------------------------------------------------
        # 6. Allow final packets to arrive
        # ----------------------------------------------------
        print("\n[6] Validating received telemetry...")
        time.sleep(1.0)

        total_messages = sum(
            len(messages) for messages in received.values()
        )

        print(f"Total MQTT messages received: {total_messages}")

        # Every core ECU must have reported telemetry.
        for ecu in ECU_TOPICS:
            count = len(received[ecu])
            print(f"  {ecu}: {count} messages")
            if count == 0:
                print(f"No telemetry received from {ecu}.")
                return 1

        # ----------------------------------------------------
        # 7. Validate envelope, topic identity and payload
        # ----------------------------------------------------
        print("\n[7] Validating message structure...")

        for ecu, messages in received.items():
            expected_topic = ECU_TOPICS[ecu]
            required = REQUIRED_FIELDS[ecu]

            sequences: list[int] = []

            for message in messages:
                if message.get("protocol_version") != 1:
                    print(f"{ecu}: invalid protocol_version")
                    return 1

                if message.get("vehicle_id") != VEHICLE_ID:
                    print(f"{ecu}: invalid vehicle_id")
                    return 1

                if message.get("ecu") != ecu:
                    print(
                        f"{ecu}: envelope ECU mismatch: "
                        f"{message.get('ecu')}"
                    )
                    return 1

                if message.get("message_type") != "telemetry":
                    print(f"{ecu}: invalid message_type")
                    return 1

                sequence = message.get("sequence")
                if not isinstance(sequence, int) or sequence < 1:
                    print(f"{ecu}: invalid sequence")
                    return 1
                sequences.append(sequence)

                if not isinstance(message.get("timestamp"), (int, float)):
                    print(f"{ecu}: invalid timestamp")
                    return 1

                data = message.get("data")
                if not isinstance(data, dict):
                    print(f"{ecu}: data is not an object")
                    return 1

                missing = required.difference(data.keys())
                if missing:
                    print(
                        f"{ecu}: missing telemetry fields: "
                        f"{sorted(missing)}"
                    )
                    return 1

            # We expect no gaps or reordering on the local QoS 1 test bus.
            expected_sequences = list(
                range(1, len(sequences) + 1)
            )

            if sequences != expected_sequences:
                print(
                    f"{ecu}: sequence validation FAILED. "
                    f"Expected {expected_sequences[:10]}... "
                    f"Received {sequences[:10]}..."
                )
                return 1

            print(
                f"  {ecu}: schema=PASSED | "
                f"topic={expected_topic} | "
                f"sequence=PASSED"
            )

        # ----------------------------------------------------
        # 8. Sanity checks across subsystems
        # ----------------------------------------------------
        print("\n[8] Cross-ECU sanity checks...")

        vcu_last = received["VCU"][-1]["data"]
        bms_last = received["BMS"][-1]["data"]
        mcu_last = received["MCU"][-1]["data"]
        tcu_last = received["TCU"][-1]["data"]

        if float(vcu_last["speed_kmh"]) < 0:
            print("VCU speed sanity check FAILED.")
            return 1

        if not 0.0 <= float(bms_last["battery_soc"]) <= 100.0:
            print("BMS SOC sanity check FAILED.")
            return 1

        if float(mcu_last["motor_rpm"]) < 0:
            print("MCU RPM sanity check FAILED.")
            return 1

        gps = tcu_last["reported_gps"]
        if not isinstance(gps, dict):
            print("TCU GPS sanity check FAILED.")
            return 1

        print("  Vehicle state ranges : PASSED")
        print("  Cross-ECU telemetry  : PASSED")

        print("\n" + "=" * 64)
        print(" PHASE 4D MULTI-ECU MQTT TEST PASSED")
        print("=" * 64)
        return 0

    except Exception as exc:
        print(f"\nPHASE 4D TEST ERROR: {exc}")
        return 1

    finally:
        print("\n[9] Cleaning up...")

        if publisher is not None:
            publisher.disconnect()

        if subscriber is not None:
            subscriber.disconnect()

        if carla_bridge is not None:
            carla_bridge.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
