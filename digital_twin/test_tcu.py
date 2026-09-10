import time

from simulation.carla_bridge import CarlaBridge
from digital_twin.vehicle_state import VehicleState
from digital_twin.tcu import TCU


def main():

    print("\n================================", flush=True)
    print(" SecureEV - Phase 2 TCU TEST", flush=True)
    print("================================\n", flush=True)

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
        # 3. Vehicle state
        # -----------------------------------------------------

        print("[5] Creating VehicleState...", flush=True)

        vehicle_state = VehicleState()

        print("[6] VehicleState created.", flush=True)

        # -----------------------------------------------------
        # 4. TCU
        # -----------------------------------------------------

        print("[7] Creating TCU...", flush=True)

        tcu = TCU(
            vehicle_state=vehicle_state,
            carla_bridge=bridge,
        )

        print("[8] TCU created successfully.", flush=True)

        # -----------------------------------------------------
        # 5. Read GPS
        # -----------------------------------------------------

        print("\n================================")
        print(" GPS TELEMETRY")
        print("================================\n", flush=True)

        for i in range(10):

            print(
                f"[GPS {i + 1:02d}] Updating TCU...",
                flush=True
            )

            tcu.tick()

            gps = vehicle_state.reported_gps

            if gps is None:
                print(
                    "ERROR: TCU did not produce GPS data.",
                    flush=True
                )
                continue

            print(
                f"GPS=("
                f"x={gps['x']:.2f}, "
                f"y={gps['y']:.2f}, "
                f"z={gps['z']:.2f}"
                f") | "
                f"Source={gps['source']}",
                flush=True
            )

            time.sleep(0.5)

        # -----------------------------------------------------
        # 6. Telemetry
        # -----------------------------------------------------

        print("\n================================")
        print(" TCU TELEMETRY")
        print("================================\n", flush=True)

        print(
            tcu.telemetry(),
            flush=True
        )

        # -----------------------------------------------------
        # 7. Success
        # -----------------------------------------------------

        print("\n================================", flush=True)
        print(" TCU TEST PASSED", flush=True)
        print("================================\n", flush=True)

    finally:

        if bridge is not None:
            bridge.cleanup()


if __name__ == "__main__":
    main()