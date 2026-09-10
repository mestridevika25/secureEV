import time

from simulation.carla_bridge import CarlaBridge
from digital_twin.vehicle_state import VehicleState
from digital_twin.vcu import VCU


def main():

    bridge = CarlaBridge()
    vehicle_state = VehicleState()

    try:
        print("\n==============================")
        print(" SecureEV - Phase 2 VCU TEST")
        print("==============================\n")

        print("[1] Spawning EV...")
        bridge.spawn_vehicle()

        print("[2] Disabling autopilot...")
        bridge.set_autopilot(False)

        print("[3] Creating VCU...")
        vcu = VCU(
            vehicle_state=vehicle_state,
            carla_bridge=bridge,
        )

        print("[4] Applying throttle...\n")

        vcu.apply_command(
            throttle=0.40,
            brake=0.0,
            steer=0.0,
        )

        for i in range(10):

            telemetry = vcu.tick()

            print(
                f"[{i + 1:02d}] "
                f"Speed={telemetry['speed_kmh']:.2f} km/h | "
                f"Acceleration={telemetry['acceleration_mps2']:.3f} m/s² | "
                f"Throttle={telemetry['throttle']:.2f}"
            )

            time.sleep(0.5)

        print("\n[5] Applying emergency brake...")

        vcu.emergency_brake()

        for i in range(5):

            telemetry = vcu.tick()

            print(
                f"[Brake {i + 1:02d}] "
                f"Speed={telemetry['speed_kmh']:.2f} km/h | "
                f"Acceleration={telemetry['acceleration_mps2']:.3f} m/s²"
            )

            time.sleep(0.5)

        print("\n==============================")
        print(" VCU TEST PASSED")
        print("==============================")

    finally:
        bridge.cleanup()


if __name__ == "__main__":
    main()