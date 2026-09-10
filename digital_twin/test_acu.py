import time

from simulation.carla_bridge import CarlaBridge
from digital_twin.vehicle_state import VehicleState
from digital_twin.vcu import VCU
from digital_twin.acu import ACU


def main():

    print("\n======================================", flush=True)
    print(" SecureEV - Phase 2 ACU TEST", flush=True)
    print("======================================\n", flush=True)

    bridge = None

    try:

        # -----------------------------------------------------
        # 1. CARLA connection
        # -----------------------------------------------------

        print("[1] Connecting to CARLA...", flush=True)

        bridge = CarlaBridge()

        print("[2] CARLA connection successful.", flush=True)

        # -----------------------------------------------------
        # 2. Spawn vehicle
        # -----------------------------------------------------

        print("[3] Spawning EV...", flush=True)

        bridge.spawn_vehicle()
        bridge.set_autopilot(False)

        print("[4] EV spawned successfully.", flush=True)

        # -----------------------------------------------------
        # 3. VehicleState
        # -----------------------------------------------------

        print("[5] Creating VehicleState...", flush=True)

        vehicle_state = VehicleState()

        print("[6] VehicleState created.", flush=True)

        # -----------------------------------------------------
        # 4. VCU
        # -----------------------------------------------------

        print("[7] Creating VCU...", flush=True)

        vcu = VCU(
            vehicle_state=vehicle_state,
            carla_bridge=bridge,
        )

        print("[8] VCU created successfully.", flush=True)

        # -----------------------------------------------------
        # 5. ACU
        # -----------------------------------------------------

        print("[9] Creating ACU...", flush=True)

        acu = ACU(
            vehicle_state=vehicle_state,
        )

        print("[10] ACU created successfully.", flush=True)

        # -----------------------------------------------------
        # 6. Initial state
        # -----------------------------------------------------

        print("\n======================================")
        print(" INITIAL ACU STATE")
        print("======================================")

        print(
            f"Autonomous Mode : "
            f"{vehicle_state.autonomous_mode}"
        )

        print(
            f"Planned Throttle: "
            f"{vehicle_state.planned_throttle}"
        )

        print(
            f"Planned Brake   : "
            f"{vehicle_state.planned_brake}"
        )

        print(
            f"Planned Steer   : "
            f"{vehicle_state.planned_steer}"
        )

        # -----------------------------------------------------
        # 7. Enable autonomous mode
        # -----------------------------------------------------

        print("\n======================================")
        print(" AUTONOMOUS MODE TEST")
        print("======================================")

        print(
            "\n[11] Enabling autonomous mode...",
            flush=True
        )

        acu.enable_autonomous_mode(
            target_speed_kmh=25.0
        )

        print(
            f"Autonomous Mode : "
            f"{vehicle_state.autonomous_mode}"
        )

        print(
            f"Target Speed    : "
            f"{acu.target_speed_kmh:.2f} km/h"
        )

        # -----------------------------------------------------
        # 8. Run ACU updates
        # -----------------------------------------------------

        print(
            "\n[12] Running ACU update loop...\n",
            flush=True
        )

        for i in range(10):

            print(
                f"[ACU {i + 1:02d}] Reading vehicle state...",
                flush=True
            )

            # Update physical state from CARLA.
            vcu.tick()

            print(
                f"[ACU {i + 1:02d}] Updating autonomous plan...",
                flush=True
            )

            # Update ACU planning.
            acu.tick()

            print(
                f"Speed={vehicle_state.speed_kmh:6.2f} km/h | "
                f"Target={acu.target_speed_kmh:6.2f} km/h | "
                f"Throttle={vehicle_state.planned_throttle:.3f} | "
                f"Brake={vehicle_state.planned_brake:.3f} | "
                f"Steer={vehicle_state.planned_steer:.3f}",
                flush=True
            )

            time.sleep(0.5)

        # -----------------------------------------------------
        # 9. Explicit planned control
        # -----------------------------------------------------

        print("\n======================================")
        print(" PLANNED CONTROL TEST")
        print("======================================")

        print(
            "\n[13] Setting explicit planned control...",
            flush=True
        )

        acu.set_planned_control(
            throttle=0.30,
            brake=0.0,
            steer=0.10,
        )

        print(
            f"Throttle = "
            f"{vehicle_state.planned_throttle:.3f}"
        )

        print(
            f"Brake    = "
            f"{vehicle_state.planned_brake:.3f}"
        )

        print(
            f"Steer    = "
            f"{vehicle_state.planned_steer:.3f}"
        )

        # -----------------------------------------------------
        # 10. Disable autonomous mode
        # -----------------------------------------------------

        print(
            "\n[14] Disabling autonomous mode...",
            flush=True
        )

        acu.disable_autonomous_mode()
        acu.tick()

        print(
            f"Autonomous Mode = "
            f"{vehicle_state.autonomous_mode}"
        )

        print(
            f"Throttle = "
            f"{vehicle_state.planned_throttle:.3f}"
        )

        print(
            f"Brake = "
            f"{vehicle_state.planned_brake:.3f}"
        )

        print(
            f"Steer = "
            f"{vehicle_state.planned_steer:.3f}"
        )

        # -----------------------------------------------------
        # 11. Telemetry
        # -----------------------------------------------------

        print("\n======================================")
        print(" ACU TELEMETRY")
        print("======================================\n")

        print(
            acu.telemetry(),
            flush=True
        )

        # -----------------------------------------------------
        # 12. Success
        # -----------------------------------------------------

        print("\n======================================")
        print(" ACU TEST PASSED")
        print("======================================\n")

    finally:

        if bridge is not None:
            bridge.cleanup()


if __name__ == "__main__":
    main()