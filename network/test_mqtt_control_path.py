"""
test_mqtt_control_path.py

SecureEV Phase 4F - MQTT command path integration test.

Pipeline under test:

    Python Publisher
        -> MQTT Broker
        -> MQTT Control Bridge
        -> queued VCU command
        -> VCU
        -> CarlaBridge
        -> CARLA vehicle

The command callback never touches CARLA directly from the MQTT network
thread. Commands are queued and executed by the main simulation thread.
"""

from __future__ import annotations

import time
import uuid

from digital_twin.digital_twin_manager import DigitalTwinManager
from digital_twin.vcu import VCU
from digital_twin.vehicle_state import VehicleState
from network.control_bridge import MQTTControlBridge
from network.control_schema import create_vcu_control_message
from network.mqtt_config import VCU_CONTROL
from network.publisher import MQTTPublisher
from network.subscriber import MQTTSubscriber
from simulation.carla_bridge import CarlaBridge


def main() -> int:
    print()
    print("=" * 66)
    print(" SecureEV - PHASE 4F MQTT COMMAND PATH TEST")
    print("=" * 66)

    bridge: CarlaBridge | None = None
    publisher: MQTTPublisher | None = None
    subscriber: MQTTSubscriber | None = None

    try:
        # ----------------------------------------------------
        # 1. CARLA
        # ----------------------------------------------------
        print("\n[1] Connecting to CARLA...")
        bridge = CarlaBridge(
            host="localhost",
            port=2000,
            timeout=10.0,
        )
        bridge.spawn_vehicle(
            blueprint_id="vehicle.tesla.model3",
            spawn_index=0,
        )
        bridge.set_autopilot(False)
        print("CARLA vehicle ready. No camera attached.")

        # ----------------------------------------------------
        # 2. Digital Twin + VCU
        # ----------------------------------------------------
        print("[2] Creating VehicleState + VCU...")
        state = VehicleState()
        vcu = VCU(state, bridge)

        manager = DigitalTwinManager(
            vehicle_state=state,
            tick_rate_hz=10.0,
        )
        manager.register_ecu(vcu)

        # ----------------------------------------------------
        # 3. MQTT subscriber / control bridge
        # ----------------------------------------------------
        print("[3] Connecting MQTT control subscriber...")
        subscriber = MQTTSubscriber(
            client_id=f"secureev-control-sub-{uuid.uuid4().hex[:8]}",
            verbose=False,
        )

        control_bridge = MQTTControlBridge(
            vcu=vcu,
            subscriber=subscriber,
        )

        if not control_bridge.start():
            print("Control subscriber setup FAILED.")
            return 1

        # ----------------------------------------------------
        # 4. MQTT publisher
        # ----------------------------------------------------
        print("[4] Connecting MQTT command publisher...")
        publisher = MQTTPublisher(
            client_id=f"secureev-control-pub-{uuid.uuid4().hex[:8]}"
        )

        if not publisher.connect():
            print("Publisher connection FAILED.")
            return 1

        time.sleep(0.5)

        sequence = 0

        def publish_command(command: str, data: dict | None = None) -> bool:
            nonlocal sequence
            sequence += 1
            message = create_vcu_control_message(
                command=command,
                data=data,
                sequence=sequence,
            )
            return publisher.publish(
                VCU_CONTROL,
                message,
                qos=1,
            )

        # ----------------------------------------------------
        # 5. Send acceleration command through MQTT
        # ----------------------------------------------------
        print("\n[5] Sending MQTT throttle command...")
        print(f"Topic: {VCU_CONTROL}")

        if not publish_command(
            "set_control",
            {
                "throttle": 0.25,
                "brake": 0.0,
                "steer": 0.0,
            },
        ):
            print("Throttle command publish FAILED.")
            return 1

        max_speed = 0.0
        start = time.time()

        while time.time() - start < 3.0:
            control_bridge.process_pending_commands()
            manager.tick()
            max_speed = max(max_speed, state.speed_kmh)
            time.sleep(0.05)

        print(f"Maximum speed after MQTT throttle: {max_speed:.2f} km/h")

        # ----------------------------------------------------
        # 6. Send braking command through MQTT
        # ----------------------------------------------------
        print("\n[6] Sending MQTT braking command...")

        if not publish_command(
            "set_control",
            {
                "throttle": 0.0,
                "brake": 0.60,
                "steer": 0.0,
            },
        ):
            print("Brake command publish FAILED.")
            return 1

        while time.time() - start < 5.5:
            control_bridge.process_pending_commands()
            manager.tick()
            time.sleep(0.05)

        print(f"Speed after braking: {state.speed_kmh:.2f} km/h")

        # ----------------------------------------------------
        # 7. Emergency brake command
        # ----------------------------------------------------
        print("\n[7] Sending MQTT emergency-brake command...")

        if not publish_command("emergency_brake"):
            print("Emergency-brake command publish FAILED.")
            return 1

        time.sleep(0.2)
        control_bridge.process_pending_commands()
        manager.tick()

        print(
            f"VCU command state: throttle={vcu.throttle:.2f} | "
            f"brake={vcu.brake:.2f} | steer={vcu.steer:.2f}"
        )

        # ----------------------------------------------------
        # 8. Validate
        # ----------------------------------------------------
        print("\n[8] Validating MQTT command path...")

        time.sleep(0.3)

        command_flow_ok = control_bridge.received_count >= 3
        accepted_ok = control_bridge.accepted_count >= 3
        rejected_ok = control_bridge.rejected_count == 0
        movement_ok = max_speed > 1.0
        emergency_brake_ok = vcu.throttle == 0.0 and vcu.brake == 1.0
        queue_ok = control_bridge.pending_count() == 0

        print(
            f"Commands received  : {control_bridge.received_count}"
        )
        print(
            f"Commands accepted  : {control_bridge.accepted_count}"
        )
        print(
            f"Commands rejected  : {control_bridge.rejected_count}"
        )
        print(f"Vehicle movement    : {'PASSED' if movement_ok else 'FAILED'}")
        print(
            f"Emergency brake     : "
            f"{'PASSED' if emergency_brake_ok else 'FAILED'}"
        )
        print(f"Command queue empty : {'PASSED' if queue_ok else 'FAILED'}")

        all_ok = (
            command_flow_ok
            and accepted_ok
            and rejected_ok
            and movement_ok
            and emergency_brake_ok
            and queue_ok
        )

        print("\n" + "=" * 66)
        if all_ok:
            print(" PHASE 4F MQTT COMMAND PATH TEST PASSED")
        else:
            print(" PHASE 4F MQTT COMMAND PATH TEST FAILED")
        print("=" * 66)

        return 0 if all_ok else 1

    except Exception as exc:
        print(f"\nPHASE 4F TEST ERROR: {exc}")
        return 1

    finally:
        print("\n[9] Cleaning up...")

        if publisher is not None:
            publisher.disconnect()

        if subscriber is not None:
            subscriber.disconnect()

        if bridge is not None:
            bridge.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
