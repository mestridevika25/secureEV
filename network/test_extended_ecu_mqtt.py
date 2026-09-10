"""
test_extended_ecu_mqtt.py

SecureEV Phase 4E - ACU + Charging + OTA live telemetry over MQTT.

Pipeline under test:
    CARLA -> Digital Twin -> core ECUs + ACU/CHG/OTA -> MQTT -> Subscriber

The camera is intentionally not attached. RGB frames are not placed on the
MQTT vehicle telemetry bus; the later dashboard will use a separate camera
transport path.
"""

from __future__ import annotations

import time
import uuid
from typing import Dict, List

from digital_twin.acu import ACU
from digital_twin.bcm import BCM
from digital_twin.bms import BMS
from digital_twin.charging_controller import ChargingController
from digital_twin.digital_twin_manager import DigitalTwinManager
from digital_twin.mcu import MCU
from digital_twin.ota_manager import OTAManager
from digital_twin.tcu import TCU
from digital_twin.vcu import VCU
from digital_twin.vehicle_state import VehicleState
from network.ecu_telemetry_bridge import ECUTelemetryBridge
from network.mqtt_config import (
    ACU_TELEMETRY,
    BMS_TELEMETRY,
    BCM_TELEMETRY,
    CHARGING_TELEMETRY,
    MCU_TELEMETRY,
    OTA_TELEMETRY,
    TCU_TELEMETRY,
    VCU_TELEMETRY,
    VEHICLE_ID,
)
from network.publisher import MQTTPublisher
from network.subscriber import MQTTSubscriber
from simulation.carla_bridge import CarlaBridge


ECU_TOPICS = {
    "VCU": VCU_TELEMETRY,
    "BMS": BMS_TELEMETRY,
    "BCM": BCM_TELEMETRY,
    "MCU": MCU_TELEMETRY,
    "TCU": TCU_TELEMETRY,
    "ACU": ACU_TELEMETRY,
    "CHG": CHARGING_TELEMETRY,
    "OTA": OTA_TELEMETRY,
}

REQUIRED_FIELDS = {
    "VCU": {"speed_kmh", "acceleration_mps2", "throttle", "brake", "steer"},
    "BMS": {
        "battery_soc",
        "battery_temp",
        "battery_capacity_kwh",
        "energy_consumed_kwh",
        "energy_charged_kwh",
    },
    "BCM": {"doors_locked", "doors_open"},
    "MCU": {"motor_rpm", "motor_temp"},
    "TCU": {"reported_gps", "gps_source"},
    "ACU": {
        "autonomous_mode",
        "control_mode",
        "target_speed_kmh",
        "planned_throttle",
        "planned_brake",
        "planned_steer",
    },
    "CHG": {
        "charging_state",
        "charger_connected",
        "charge_port_locked",
        "charging_power_kw",
        "vehicle_disabled_flag",
        "fault_reason",
        "last_command",
    },
    "OTA": {
        "firmware_version",
        "update_state",
        "pending_version",
        "pending_package_hash",
        "pending_signature_valid",
        "previous_firmware_version",
        "last_error",
    },
}


def _sequences_are_contiguous(messages: List[dict]) -> bool:
    if not messages:
        return False

    sequences = [message.get("sequence") for message in messages]
    return sequences == list(range(1, len(sequences) + 1))


def _validate_envelope(
    ecu_id: str,
    topic: str,
    messages: List[dict],
) -> bool:
    if not messages:
        return False

    for message in messages:
        if message.get("protocol_version") != 1:
            return False
        if message.get("vehicle_id") != VEHICLE_ID:
            return False
        if str(message.get("ecu", "")).upper() != ecu_id:
            return False
        if message.get("message_type") != "telemetry":
            return False
        if not isinstance(message.get("message_id"), str):
            return False
        if not isinstance(message.get("timestamp"), (int, float)):
            return False
        if not isinstance(message.get("sequence"), int):
            return False
        if not isinstance(message.get("data"), dict):
            return False

        data = message["data"]
        if not REQUIRED_FIELDS[ecu_id].issubset(data.keys()):
            return False

        if message.get("topic") is not None and message["topic"] != topic:
            return False

    return _sequences_are_contiguous(messages)


def main() -> int:
    print()
    print("=" * 68)
    print(" SecureEV - PHASE 4E EXTENDED ECU MQTT TEST")
    print("=" * 68)

    carla_bridge: CarlaBridge | None = None
    publisher: MQTTPublisher | None = None
    subscriber: MQTTSubscriber | None = None

    received: Dict[str, List[dict]] = {
        ecu_id: [] for ecu_id in ECU_TOPICS
    }

    def on_message(topic: str, payload: dict) -> None:
        for ecu_id, expected_topic in ECU_TOPICS.items():
            if topic == expected_topic:
                received[ecu_id].append(payload)
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
        carla_bridge.set_autopilot(False)
        print("CARLA vehicle ready. No camera attached.")

        # ----------------------------------------------------
        # 2. Digital Twin
        # ----------------------------------------------------
        print("[2] Creating eight networked EV modules...")

        state = VehicleState()
        state.battery_soc = 80.0

        vcu = VCU(state, carla_bridge)
        charging = ChargingController(state, charging_power_kw=11.0)
        bms = BMS(
            state,
            vcu=vcu,
            charging_controller=charging,
        )
        bcm = BCM(state)
        mcu = MCU(state, vcu=vcu)
        tcu = TCU(state, carla_bridge)
        acu = ACU(state)
        ota = OTAManager(state)

        manager = DigitalTwinManager(
            vehicle_state=state,
            tick_rate_hz=10.0,
        )

        for ecu in (
            vcu,
            bms,
            bcm,
            mcu,
            tcu,
            acu,
            charging,
            ota,
        ):
            manager.register_ecu(ecu)

        print("Registered modules:")
        for ecu_id in manager.ecus:
            print(f"  - {ecu_id}: ONLINE")

        # ----------------------------------------------------
        # 3. MQTT subscriber
        # ----------------------------------------------------
        print("\n[3] Connecting MQTT subscriber...")
        subscriber = MQTTSubscriber(
            client_id=f"secureev-extended-sub-{uuid.uuid4().hex[:8]}",
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
            client_id=f"secureev-extended-pub-{uuid.uuid4().hex[:8]}"
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
        # 5. Exercise extended modules
        # ----------------------------------------------------
        print("\n[5] Exercising ACU + CHG + OTA states...")

        # Safe initial state.
        vcu.emergency_brake()
        manager.tick()

        # ACU autonomous planning while vehicle is stationary.
        acu.enable_autonomous_mode(target_speed_kmh=20.0)
        manager.tick()

        # Start a short charging session.
        charging.connect_charger()
        charging.start_charging()

        for _ in range(10):
            manager.tick()
            time.sleep(0.05)

        charging.stop_charging()
        charging.disconnect_charger()

        # Valid OTA update.
        package = b"SecureEV Phase 4E firmware 1.2.0"
        package_hash = ota.stage_update(
            version="1.2.0",
            package_data=package,
            signature_valid=True,
        )
        ota_success = ota.install_update()

        # Tampered OTA must be rejected and must not change firmware.
        ota.stage_update(
            version="9.9.9",
            package_data=b"tampered firmware package",
            signature_valid=False,
        )
        tampered_ota_result = ota.install_update()

        acu.disable_autonomous_mode()

        print(
            f"ACU mode={acu.control_mode} | "
            f"target={acu.target_speed_kmh:.1f} km/h"
        )
        print(
            f"CHG state={state.charging_state} | "
            f"SOC={state.battery_soc:.2f}%"
        )
        print(
            f"OTA success={ota_success} | "
            f"firmware={state.firmware_version} | "
            f"SHA256={package_hash[:16]}..."
        )
        print(
            f"Tampered OTA accepted={tampered_ota_result} | "
            f"state={ota.update_state} | "
            f"firmware still={state.firmware_version}"
        )

        if not ota_success or tampered_ota_result:
            print("OTA behavioral test FAILED.")
            return 1

        # ----------------------------------------------------
        # 6. Publish all eight modules
        # ----------------------------------------------------
        print("\n[6] Publishing live telemetry from eight networked modules...")
        print("      VCU | BMS | BCM | MCU | TCU | ACU | CHG | OTA")

        start = time.time()
        duration = 6.0
        last_printed_second = -1

        while time.time() - start < duration:
            elapsed = time.time() - start

            # Controlled vehicle motion while keeping the test finite.
            if elapsed < 2.0:
                vcu.apply_command(
                    throttle=0.18,
                    brake=0.0,
                    steer=0.03,
                )
                phase = "ACCELERATING"
            elif elapsed < 4.0:
                vcu.apply_command(
                    throttle=0.0,
                    brake=0.25,
                    steer=0.0,
                )
                phase = "BRAKING"
            else:
                vcu.emergency_brake()
                phase = "STOPPED"

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
                    f"SOC={all_telemetry['BMS']['battery_soc']:6.2f}% | "
                    f"RPM={all_telemetry['MCU']['motor_rpm']:7.1f} | "
                    f"ACU={all_telemetry['ACU']['control_mode']:10s} | "
                    f"CHG={all_telemetry['CHG']['charging_state']:9s} | "
                    f"OTA={all_telemetry['OTA']['firmware_version']} | "
                    f"published={published_count}/8"
                )

            time.sleep(0.1)

        vcu.emergency_brake()
        manager.tick()
        time.sleep(0.5)

        # ----------------------------------------------------
        # 7. Validate received telemetry
        # ----------------------------------------------------
        print("\n[7] Validating received telemetry...")

        total_messages = sum(len(items) for items in received.values())
        print(f"Total MQTT messages received: {total_messages}")

        all_ok = True

        for ecu_id, topic in ECU_TOPICS.items():
            count = len(received[ecu_id])
            sequence_ok = _sequences_are_contiguous(received[ecu_id])
            envelope_ok = _validate_envelope(
                ecu_id,
                topic,
                received[ecu_id],
            )

            print(
                f"  {ecu_id}: messages={count} | "
                f"schema={'PASSED' if envelope_ok else 'FAILED'} | "
                f"sequence={'PASSED' if sequence_ok else 'FAILED'}"
            )

            if count == 0 or not sequence_ok or not envelope_ok:
                all_ok = False

        # ----------------------------------------------------
        # 8. Extended module sanity checks
        # ----------------------------------------------------
        print("\n[8] Extended module sanity checks...")

        acu_ok = (
            0.0 <= state.planned_throttle <= 1.0
            and 0.0 <= state.planned_brake <= 1.0
            and -1.0 <= state.planned_steer <= 1.0
        )

        charging_ok = (
            state.charging_state in ChargingController.VALID_STATES
            and state.charge_port_locked is True
            and state.vehicle_disabled_flag is False
        )

        ota_ok = (
            state.firmware_version == "1.2.0"
            and ota.update_state == "rejected"
        )

        bms_ok = 0.0 <= state.battery_soc <= 100.0

        print(f"  ACU planned controls : {'PASSED' if acu_ok else 'FAILED'}")
        print(f"  Charging state       : {'PASSED' if charging_ok else 'FAILED'}")
        print(f"  OTA behavior         : {'PASSED' if ota_ok else 'FAILED'}")
        print(f"  Battery range        : {'PASSED' if bms_ok else 'FAILED'}")

        if not all((acu_ok, charging_ok, ota_ok, bms_ok)):
            all_ok = False

        # ----------------------------------------------------
        # 9. Cleanup
        # ----------------------------------------------------
        print("\n[9] Cleaning up...")
        acu.disable_autonomous_mode()
        charging.stop_charging()

        print()
        print("=" * 68)
        if all_ok:
            print(" PHASE 4E EXTENDED ECU MQTT TEST PASSED")
        else:
            print(" PHASE 4E EXTENDED ECU MQTT TEST FAILED")
        print("=" * 68)

        return 0 if all_ok else 1

    except Exception as exc:
        print(f"\n[ERROR] Phase 4E test failed: {exc}")
        return 1

    finally:
        if subscriber is not None:
            subscriber.disconnect()
        if publisher is not None:
            publisher.disconnect()
        if carla_bridge is not None:
            carla_bridge.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
