"""
test_phase6_control_injection.py

SecureEV Phase 6A - controlled Red Team control-injection test.

Pipeline under test:

    Red Team attacker
        -> MQTT publisher
        -> Mosquitto
        -> Phase 5 Security Gateway
        -> ALLOW/BLOCK
        -> VCU command queue
        -> VCU -> CarlaBridge -> CARLA

This version adds explicit synchronization between the asynchronous MQTT
callback and the main simulation loop.  The test waits for the gateway
inspection AND for the corresponding VCU command state to be applied before
measuring physical vehicle movement.  This avoids a timing race where the
security gateway has already counted a message but the command has not yet
been drained from the queue.
"""

from __future__ import annotations

import time
import uuid

from blue_team.security_gateway import SecurityGateway
from digital_twin.digital_twin_manager import DigitalTwinManager
from digital_twin.vcu import VCU
from digital_twin.vehicle_state import VehicleState
from network.control_bridge import MQTTControlBridge
from network.control_schema import create_vcu_control_message
from network.mqtt_config import VCU_CONTROL
from network.publisher import MQTTPublisher
from network.subscriber import MQTTSubscriber
from red_team.attack_manager import AttackManager
from red_team.control_injection import ControlInjectionAttacker
from simulation.carla_bridge import CarlaBridge


def wait_for_gateway_decision(
    gateway: SecurityGateway,
    expected_count: int,
    expected_message_id: str,
    timeout: float = 2.0,
) -> bool:
    """Wait until the callback has fully recorded the expected decision."""
    deadline = time.time() + timeout

    while time.time() < deadline:
        decision = gateway.last_decision
        if (
            gateway.checked_count >= expected_count
            and decision is not None
            and decision.message_id == expected_message_id
        ):
            return True
        time.sleep(0.02)

    decision = gateway.last_decision
    return bool(
        gateway.checked_count >= expected_count
        and decision is not None
        and decision.message_id == expected_message_id
    )


def tick_for(
    manager: DigitalTwinManager,
    bridge: MQTTControlBridge,
    duration: float,
) -> float:
    """Run the simulation loop and return maximum observed speed."""
    deadline = time.time() + duration
    max_speed = 0.0

    while time.time() < deadline:
        bridge.process_pending_commands()
        manager.tick()
        max_speed = max(max_speed, float(manager.vehicle_state.speed_kmh))
        time.sleep(0.05)

    return max_speed


def wait_for_vcu_control_state(
    manager: DigitalTwinManager,
    bridge: MQTTControlBridge,
    vcu: VCU,
    *,
    throttle: float,
    brake: float,
    steer: float,
    timeout: float = 2.0,
) -> bool:
    """Wait until a queued MQTT command has actually reached the VCU."""
    deadline = time.time() + timeout

    while time.time() < deadline:
        bridge.process_pending_commands()
        manager.tick()

        if (
            abs(vcu.throttle - throttle) < 1e-6
            and abs(vcu.brake - brake) < 1e-6
            and abs(vcu.steer - steer) < 1e-6
        ):
            return True

        time.sleep(0.05)

    return (
        abs(vcu.throttle - throttle) < 1e-6
        and abs(vcu.brake - brake) < 1e-6
        and abs(vcu.steer - steer) < 1e-6
    )


def publish_legitimate(
    publisher: MQTTPublisher,
    sequence: int,
    command: str,
    data: dict | None = None,
) -> dict:
    """Create and publish one legitimate VCU command."""
    message = create_vcu_control_message(
        command=command,
        data=data,
        sequence=sequence,
    )

    if not publisher.publish(VCU_CONTROL, message, qos=1):
        raise RuntimeError(f"Failed to publish legitimate command: {command}")

    return message


def main() -> int:
    print()
    print("=" * 70)
    print(" SecureEV - PHASE 6A RED TEAM CONTROL-INJECTION TEST")
    print("=" * 70)

    carla_bridge: CarlaBridge | None = None
    publisher: MQTTPublisher | None = None
    subscriber: MQTTSubscriber | None = None
    control_bridge: MQTTControlBridge | None = None

    try:
        # ------------------------------------------------------------
        # 1. CARLA
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
        print("CARLA vehicle ready. No camera attached.")

        # ------------------------------------------------------------
        # 2. Vehicle + VCU + manager
        # ------------------------------------------------------------
        print("[2] Creating VehicleState + VCU...")
        state = VehicleState()
        vcu = VCU(state, carla_bridge)

        manager = DigitalTwinManager(
            vehicle_state=state,
            tick_rate_hz=10.0,
        )
        manager.register_ecu(vcu)

        # ------------------------------------------------------------
        # 3. Phase 5 security gateway + protected command path
        # ------------------------------------------------------------
        print("[3] Creating Phase 5 Security Gateway + protected control path...")
        gateway = SecurityGateway()

        subscriber = MQTTSubscriber(
            client_id=f"secureev-phase6-sub-{uuid.uuid4().hex[:8]}",
            verbose=False,
        )
        control_bridge = MQTTControlBridge(
            vcu=vcu,
            subscriber=subscriber,
            security_gateway=gateway,
        )

        if not control_bridge.start():
            print("Protected control path setup FAILED.")
            return 1

        print("Protected subscription: secureev/+/control")
        print("Blue Team control: Security Gateway")

        # ------------------------------------------------------------
        # 4. Red Team publisher
        # ------------------------------------------------------------
        print("[4] Connecting Red Team MQTT publisher...")
        publisher = MQTTPublisher(
            client_id=f"secureev-redteam-{uuid.uuid4().hex[:8]}"
        )

        if not publisher.connect():
            print("Red Team publisher connection FAILED.")
            return 1

        attacker = ControlInjectionAttacker(publisher=publisher)
        attack_manager = AttackManager(attacker)

        # Allow both MQTT connections/subscriptions to settle.
        time.sleep(0.5)

        # ------------------------------------------------------------
        # 5. Legitimate baseline
        # ------------------------------------------------------------
        print("\n[5] Sending legitimate throttle command to establish baseline...")
        valid_throttle = publish_legitimate(
            publisher,
            sequence=1,
            command="set_control",
            data={
                "throttle": 0.30,
                "brake": 0.0,
                "steer": 0.0,
            },
        )

        if not wait_for_gateway_decision(
            gateway,
            expected_count=1,
            expected_message_id=valid_throttle["message_id"],
        ):
            print("Gateway did not fully record baseline command.")
            return 1

        if not wait_for_vcu_control_state(
            manager,
            control_bridge,
            vcu,
            throttle=0.30,
            brake=0.0,
            steer=0.0,
        ):
            print("Baseline VCU command was not applied.")
            return 1

        max_speed = tick_for(manager, control_bridge, 2.0)
        print(f"Baseline maximum speed: {max_speed:.2f} km/h")

        if max_speed <= 1.0:
            print("Baseline movement FAILED.")
            return 1

        # ------------------------------------------------------------
        # 6. Legitimate braking command
        # ------------------------------------------------------------
        print("\n[6] Sending legitimate braking command...")
        valid_brake = publish_legitimate(
            publisher,
            sequence=2,
            command="set_control",
            data={
                "throttle": 0.0,
                "brake": 0.70,
                "steer": 0.0,
            },
        )

        if not wait_for_gateway_decision(
            gateway,
            expected_count=2,
            expected_message_id=valid_brake["message_id"],
        ):
            print("Gateway did not fully record braking command.")
            return 1

        if not wait_for_vcu_control_state(
            manager,
            control_bridge,
            vcu,
            throttle=0.0,
            brake=0.70,
            steer=0.0,
        ):
            print("Braking command was not applied to the VCU.")
            return 1

        tick_for(manager, control_bridge, 1.5)
        print(f"Speed before Red Team attacks: {state.speed_kmh:.2f} km/h")

        if state.speed_kmh > 1.0:
            print("Vehicle did not stop before attack phase.")
            return 1

        # ------------------------------------------------------------
        # 7. Launch controlled attacks.
        # All blocked attacks reuse sequence=3. If the gateway incorrectly
        # consumes blocked sequences, the final legitimate sequence=3 command
        # will be rejected.
        # ------------------------------------------------------------
        print("\n[7] Launching controlled Red Team control injections...")

        scenarios = [
            attacker.unauthorized_acceleration(sequence=3),
            attacker.out_of_range_control(sequence=3),
            attacker.replay_control(valid_throttle),
            attacker.unauthorized_command(sequence=3),
        ]

        attack_results: list[bool] = []
        expected_checks = gateway.checked_count

        for index, scenario in enumerate(scenarios, start=1):
            print(f"  [{index}] {scenario.name}...")
            print(f"      {scenario.description}")

            if not attack_manager.launch(scenario):
                print(f"Attack publish FAILED: {scenario.name}")
                return 1

            expected_checks += 1
            if not wait_for_gateway_decision(
                gateway,
                expected_count=expected_checks,
                expected_message_id=scenario.message["message_id"],
            ):
                print(f"Gateway did not fully inspect attack: {scenario.name}")
                return 1

            decision = gateway.last_decision
            allowed = bool(decision and decision.allowed)
            reason = decision.reason if decision else "no decision"

            print(
                f"      Gateway: {'ALLOW' if allowed else 'BLOCK'} "
                f"| reason={reason}"
            )

            passed = (
                not allowed
                and decision is not None
                and decision.reason == scenario.expected_reason
            )
            attack_results.append(passed)

            if not passed:
                print(
                    f"      EXPECTED BLOCK ({scenario.expected_reason}) "
                    f"but received {reason}"
                )
                return 1

            # A blocked attack must not alter the VCU control state.
            tick_for(manager, control_bridge, 0.20)

        blocked_control_state_ok = (
            vcu.throttle == 0.0
            and vcu.brake == 0.70
            and vcu.steer == 0.0
            and control_bridge.pending_count() == 0
        )

        print(f"\nBlocked attacks: {sum(attack_results)}/{len(attack_results)}")
        print(
            "VCU command state after attacks: "
            f"throttle={vcu.throttle:.2f} | "
            f"brake={vcu.brake:.2f} | "
            f"steer={vcu.steer:.2f}"
        )

        # ------------------------------------------------------------
        # 8. Legitimate sequence=3 after blocked attacks.
        # ------------------------------------------------------------
        print("\n[8] Sending legitimate emergency-brake after attacks...")
        valid_emergency = publish_legitimate(
            publisher,
            sequence=3,
            command="emergency_brake",
        )

        expected_checks += 1
        if not wait_for_gateway_decision(
            gateway,
            expected_count=expected_checks,
            expected_message_id=valid_emergency["message_id"],
        ):
            print("Gateway did not fully record emergency-brake command.")
            return 1

        if not wait_for_vcu_control_state(
            manager,
            control_bridge,
            vcu,
            throttle=0.0,
            brake=1.0,
            steer=0.0,
        ):
            print("Emergency-brake command was not applied to the VCU.")
            return 1

        final_decision = gateway.last_decision
        emergency_ok = bool(
            final_decision
            and final_decision.allowed
            and final_decision.sequence == 3
            and vcu.throttle == 0.0
            and vcu.brake == 1.0
            and vcu.steer == 0.0
        )

        # ------------------------------------------------------------
        # 9. Security validation
        # ------------------------------------------------------------
        print("\n[9] Validating Phase 6A Red Team behavior...")
        print(f"Attack scenarios launched : {attack_manager.successful_launches()}")
        print(f"Attack scenarios failed   : {attack_manager.failed_launches()}")
        print(f"Gateway checked           : {gateway.checked_count}")
        print(f"Gateway allowed           : {gateway.allowed_count}")
        print(f"Gateway blocked           : {gateway.blocked_count}")
        print(f"Bridge accepted           : {control_bridge.accepted_count}")
        print(f"Bridge rejected           : {control_bridge.rejected_count}")
        print(
            f"Blocked injection tests   : "
            f"{'PASSED' if all(attack_results) else 'FAILED'}"
        )
        print(
            f"No physical control change: "
            f"{'PASSED' if blocked_control_state_ok else 'FAILED'}"
        )
        print(
            f"Sequence preserved        : "
            f"{'PASSED' if gateway.get_last_sequence(VCU_CONTROL) == 3 else 'FAILED'}"
        )
        print(
            f"Legitimate command after attacks: "
            f"{'PASSED' if emergency_ok else 'FAILED'}"
        )
        print(
            f"Command queue empty       : "
            f"{'PASSED' if control_bridge.pending_count() == 0 else 'FAILED'}"
        )

        all_ok = all(
            [
                max_speed > 1.0,
                len(attack_results) == 4,
                all(attack_results),
                blocked_control_state_ok,
                gateway.blocked_count >= 4,
                gateway.get_last_sequence(VCU_CONTROL) == 3,
                emergency_ok,
                control_bridge.pending_count() == 0,
            ]
        )

        print("\n" + "=" * 70)
        if all_ok:
            print(" PHASE 6A RED TEAM CONTROL-INJECTION TEST PASSED")
        else:
            print(" PHASE 6A RED TEAM CONTROL-INJECTION TEST FAILED")
        print("=" * 70)

        print("\nAttack summary:")
        for record in attack_manager.summary():
            print(
                f"  {record['name']}: published={record['published']} "
                f"| expected={record['expected_reason']}"
            )

        return 0 if all_ok else 1

    except Exception as exc:
        print(f"\nPHASE 6A TEST ERROR: {exc}")
        return 1

    finally:
        print("\n[10] Cleaning up...")

        if publisher is not None:
            publisher.disconnect()

        if subscriber is not None:
            subscriber.disconnect()

        if carla_bridge is not None:
            carla_bridge.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
