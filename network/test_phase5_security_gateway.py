"""
test_phase5_security_gateway.py

SecureEV Phase 5 integration test.

Demonstrates:
    legitimate MQTT command
        -> security gateway
        -> VCU
        -> CARLA

and controlled security checks for:
    - replay
    - non-monotonic sequence
    - stale message
    - wrong vehicle ID
    - unauthorized command
    - unexpected topic

A blocked message never reaches the VCU command queue.
"""

from __future__ import annotations

import copy
import time
import uuid

from blue_team.security_gateway import SecurityGateway
from digital_twin.digital_twin_manager import DigitalTwinManager
from digital_twin.vcu import VCU
from digital_twin.vehicle_state import VehicleState
from network.control_bridge import MQTTControlBridge
from network.control_schema import create_vcu_control_message
from network.mqtt_config import BCM_CONTROL, VCU_CONTROL
from network.publisher import MQTTPublisher
from network.subscriber import MQTTSubscriber
from simulation.carla_bridge import CarlaBridge


def wait_for_commands(
    control_bridge: MQTTControlBridge,
    manager: DigitalTwinManager,
    seconds: float,
) -> None:
    """Run the simulation loop while MQTT callbacks enqueue commands."""
    end_time = time.time() + seconds
    while time.time() < end_time:
        control_bridge.process_pending_commands()
        manager.tick()
        time.sleep(0.05)


def publish_and_process(
    publisher: MQTTPublisher,
    control_bridge: MQTTControlBridge,
    manager: DigitalTwinManager,
    topic: str,
    message: dict,
    settle_seconds: float = 0.4,
) -> bool:
    published = publisher.publish(topic, message, qos=1)
    if not published:
        return False
    wait_for_commands(control_bridge, manager, settle_seconds)
    return True


def main() -> int:
    print()
    print("=" * 70)
    print(" SecureEV - PHASE 5 SECURITY GATEWAY TEST")
    print("=" * 70)

    bridge: CarlaBridge | None = None
    publisher: MQTTPublisher | None = None
    subscriber: MQTTSubscriber | None = None

    try:
        # ------------------------------------------------------------
        # 1. CARLA
        # ------------------------------------------------------------
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

        # ------------------------------------------------------------
        # 2. Vehicle state + VCU
        # ------------------------------------------------------------
        print("[2] Creating VehicleState + VCU...")
        state = VehicleState()
        vcu = VCU(state, bridge)
        manager = DigitalTwinManager(
            vehicle_state=state,
            tick_rate_hz=10.0,
        )
        manager.register_ecu(vcu)

        # ------------------------------------------------------------
        # 3. Security gateway
        # ------------------------------------------------------------
        print("[3] Creating Phase 5 Security Gateway...")
        gateway = SecurityGateway(
            expected_vehicle_id="SEV-001",
            max_message_age_seconds=5.0,
            max_future_skew_seconds=2.0,
        )

        # ------------------------------------------------------------
        # 4. MQTT control path
        # ------------------------------------------------------------
        print("[4] Connecting MQTT subscriber + protected control path...")
        subscriber = MQTTSubscriber(
            client_id=f"secureev-security-sub-{uuid.uuid4().hex[:8]}",
            verbose=False,
        )
        control_bridge = MQTTControlBridge(
            vcu=vcu,
            subscriber=subscriber,
            security_gateway=gateway,
        )

        if not control_bridge.start():
            print("Security control subscriber setup FAILED.")
            return 1

        print("Protected subscription: secureev/+/control")
        print("Gateway policy: exact VCU control topic only")

        # ------------------------------------------------------------
        # 5. Publisher
        # ------------------------------------------------------------
        print("[5] Connecting MQTT command publisher...")
        publisher = MQTTPublisher(
            client_id=f"secureev-security-pub-{uuid.uuid4().hex[:8]}"
        )
        if not publisher.connect():
            print("Publisher connection FAILED.")
            return 1
        time.sleep(0.5)

        sequence = 0

        def new_vcu_command(
            command: str,
            data: dict | None = None,
        ) -> dict:
            nonlocal sequence
            sequence += 1
            return create_vcu_control_message(
                command=command,
                data=data,
                sequence=sequence,
            )

        # ------------------------------------------------------------
        # 6. Legitimate command #1
        # ------------------------------------------------------------
        print("\n[6] Sending legitimate MQTT throttle command...")
        valid_throttle = new_vcu_command(
            "set_control",
            {
                "throttle": 0.30,
                "brake": 0.0,
                "steer": 0.0,
            },
        )
        if not publish_and_process(
            publisher,
            control_bridge,
            manager,
            VCU_CONTROL,
            valid_throttle,
            settle_seconds=2.0,
        ):
            print("Throttle publish FAILED.")
            return 1

        max_speed = state.speed_kmh
        print(f"Maximum speed after valid command: {max_speed:.2f} km/h")

        # ------------------------------------------------------------
        # 7. Legitimate command #2
        # ------------------------------------------------------------
        print("\n[7] Sending legitimate MQTT braking command...")
        valid_brake = new_vcu_command(
            "set_control",
            {
                "throttle": 0.0,
                "brake": 0.60,
                "steer": 0.0,
            },
        )
        if not publish_and_process(
            publisher,
            control_bridge,
            manager,
            VCU_CONTROL,
            valid_brake,
            settle_seconds=1.0,
        ):
            print("Brake publish FAILED.")
            return 1
        print(f"Speed after valid braking: {state.speed_kmh:.2f} km/h")

        # ------------------------------------------------------------
        # 8. Controlled attack cases
        # ------------------------------------------------------------
        print("\n[8] Running controlled security checks...")

        blocked_before = gateway.blocked_count

        # 8A. Replay the already accepted brake message.
        print("  [A] Replay attack...")
        if not publish_and_process(
            publisher,
            control_bridge,
            manager,
            VCU_CONTROL,
            copy.deepcopy(valid_brake),
        ):
            print("Replay publish FAILED.")
            return 1
        replay_ok = gateway.last_decision is not None and (
            gateway.last_decision.reason == "replay detected"
        )

        # 8B. New message ID, but old sequence number.
        print("  [B] Non-monotonic sequence attack...")
        out_of_order = new_vcu_command(
            "emergency_brake",
        )
        out_of_order["sequence"] = 2
        out_of_order["message_id"] = str(uuid.uuid4())
        if not publish_and_process(
            publisher,
            control_bridge,
            manager,
            VCU_CONTROL,
            out_of_order,
        ):
            print("Sequence attack publish FAILED.")
            return 1
        sequence_ok = gateway.last_decision is not None and (
            gateway.last_decision.reason == "non-monotonic sequence"
        )

        # 8C. Stale message. Sequence is 3, but it must not consume it.
        print("  [C] Stale-message attack...")
        stale_message = new_vcu_command("emergency_brake")
        stale_message["sequence"] = 3
        stale_message["timestamp"] = time.time() - 30.0
        if not publish_and_process(
            publisher,
            control_bridge,
            manager,
            VCU_CONTROL,
            stale_message,
        ):
            print("Stale-message publish FAILED.")
            return 1
        stale_ok = gateway.last_decision is not None and (
            gateway.last_decision.reason == "stale message"
        )

        # 8D. Wrong vehicle identity. Also must not consume sequence 3.
        print("  [D] Wrong vehicle identity...")
        wrong_vehicle = new_vcu_command("emergency_brake")
        wrong_vehicle["sequence"] = 3
        wrong_vehicle["vehicle_id"] = "ATTACKER-001"
        if not publish_and_process(
            publisher,
            control_bridge,
            manager,
            VCU_CONTROL,
            wrong_vehicle,
        ):
            print("Wrong-vehicle publish FAILED.")
            return 1
        identity_ok = gateway.last_decision is not None and (
            gateway.last_decision.reason == "unexpected vehicle_id"
        )

        # 8E. Unauthorized command. Manually mutate a valid envelope.
        print("  [E] Unauthorized-command injection...")
        unauthorized = new_vcu_command("emergency_brake")
        unauthorized["sequence"] = 3
        unauthorized["data"]["command"] = "remote_unlock"
        if not publish_and_process(
            publisher,
            control_bridge,
            manager,
            VCU_CONTROL,
            unauthorized,
        ):
            print("Unauthorized command publish FAILED.")
            return 1
        command_ok = gateway.last_decision is not None and (
            gateway.last_decision.reason == "unsupported command"
        )

        # 8F. Valid VCU payload on another ECU's topic.
        print("  [F] Unexpected-topic injection...")
        wrong_topic = new_vcu_command("emergency_brake")
        wrong_topic["sequence"] = 3
        if not publish_and_process(
            publisher,
            control_bridge,
            manager,
            BCM_CONTROL,
            wrong_topic,
        ):
            print("Wrong-topic publish FAILED.")
            return 1
        topic_ok = gateway.last_decision is not None and (
            gateway.last_decision.reason == "unexpected topic"
        )

        blocked_attacks = gateway.blocked_count - blocked_before
        print(f"Blocked attack messages: {blocked_attacks}")

        # ------------------------------------------------------------
        # 9. Prove a legitimate seq=3 still works after blocked attacks.
        # ------------------------------------------------------------
        print("\n[9] Sending legitimate emergency-brake after attacks...")
        valid_emergency = new_vcu_command("emergency_brake")
        valid_emergency["sequence"] = 3
        if not publish_and_process(
            publisher,
            control_bridge,
            manager,
            VCU_CONTROL,
            valid_emergency,
            settle_seconds=0.6,
        ):
            print("Emergency-brake publish FAILED.")
            return 1

        emergency_ok = (
            vcu.throttle == 0.0
            and vcu.brake == 1.0
            and gateway.last_decision is not None
            and gateway.last_decision.allowed
            and gateway.last_decision.sequence == 3
        )

        queue_ok = control_bridge.pending_count() == 0

        # ------------------------------------------------------------
        # 10. Validation
        # ------------------------------------------------------------
        print("\n[10] Validating Phase 5 security behavior...")
        print(f"Gateway checked : {gateway.checked_count}")
        print(f"Gateway allowed : {gateway.allowed_count}")
        print(f"Gateway blocked : {gateway.blocked_count}")
        print(f"Bridge accepted : {control_bridge.accepted_count}")
        print(f"Bridge rejected : {control_bridge.rejected_count}")
        print(f"Last sequence   : {gateway.get_last_sequence(VCU_CONTROL)}")
        print(f"Replay defense  : {'PASSED' if replay_ok else 'FAILED'}")
        print(f"Sequence defense: {'PASSED' if sequence_ok else 'FAILED'}")
        print(f"Freshness check : {'PASSED' if stale_ok else 'FAILED'}")
        print(f"Identity check  : {'PASSED' if identity_ok else 'FAILED'}")
        print(f"Command policy  : {'PASSED' if command_ok else 'FAILED'}")
        print(f"Topic policy    : {'PASSED' if topic_ok else 'FAILED'}")
        print(f"Emergency brake : {'PASSED' if emergency_ok else 'FAILED'}")
        print(f"Queue empty     : {'PASSED' if queue_ok else 'FAILED'}")

        all_ok = all(
            [
                max_speed > 1.0,
                blocked_attacks >= 6,
                replay_ok,
                sequence_ok,
                stale_ok,
                identity_ok,
                command_ok,
                topic_ok,
                emergency_ok,
                queue_ok,
            ]
        )

        print("\n" + "=" * 70)
        if all_ok:
            print(" PHASE 5 SECURITY GATEWAY TEST PASSED")
        else:
            print(" PHASE 5 SECURITY GATEWAY TEST FAILED")
        print("=" * 70)

        print("\nSecurity event summary:")
        for reason, count in sorted(gateway.get_reason_counts().items()):
            print(f"  {reason}: {count}")

        return 0 if all_ok else 1

    except Exception as exc:
        print(f"\nPHASE 5 TEST ERROR: {exc}")
        return 1

    finally:
        print("\n[11] Cleaning up...")
        if publisher is not None:
            publisher.disconnect()
        if subscriber is not None:
            subscriber.disconnect()
        if bridge is not None:
            bridge.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
