import time

from simulation.carla_bridge import CarlaBridge
from digital_twin.vehicle_state import VehicleState
from digital_twin.vcu import VCU
from digital_twin.mcu import MCU


def main():

    print("\n================================")
    print(" SecureEV - Phase 2 MCU TEST")
    print("================================\n")

    print("[1] Connecting to CARLA...", flush=True)

    bridge = CarlaBridge()

    print("[2] CARLA connection successful.", flush=True)

    vehicle_state = VehicleState()

    try:

        print("[3] Spawning EV...", flush=True)

        bridge.spawn_vehicle()
        bridge.set_autopilot(False)

        print("[4] Creating VCU...", flush=True)

        vcu = VCU(
            vehicle_state=vehicle_state,
            carla_bridge=bridge,
        )

        print("[5] Creating MCU...", flush=True)

        mcu = MCU(
            vehicle_state=vehicle_state,
            vcu=vcu,
        )

        print("\nInitial Motor State:")
        print(
            f"Motor RPM  : {vehicle_state.motor_rpm:.2f}"
        )
        print(
            f"Motor Temp : {vehicle_state.motor_temp:.2f} °C"
        )

        print("\n[6] Applying throttle...", flush=True)

        vcu.apply_command(
            throttle=0.50,
            brake=0.0,
            steer=0.0,
        )

        print("[7] Starting motor simulation...\n", flush=True)

        for i in range(20):

            vcu.tick()
            mcu.tick()

            print(
                f"[{i + 1:02d}] "
                f"Speed={vehicle_state.speed_kmh:6.2f} km/h | "
                f"RPM={vehicle_state.motor_rpm:8.2f} | "
                f"MotorTemp={vehicle_state.motor_temp:6.2f} °C",
                flush=True
            )

            time.sleep(0.5)

        print("\n[8] Applying emergency brake...", flush=True)

        vcu.emergency_brake()

        for i in range(8):

            vcu.tick()
            mcu.tick()

            print(
                f"[Brake {i + 1:02d}] "
                f"Speed={vehicle_state.speed_kmh:6.2f} km/h | "
                f"RPM={vehicle_state.motor_rpm:8.2f} | "
                f"MotorTemp={vehicle_state.motor_temp:6.2f} °C",
                flush=True
            )

            time.sleep(0.5)

        print("\nMCU Telemetry:")
        print(mcu.telemetry())

        print("\n================================")
        print(" MCU TEST PASSED")
        print("================================\n")

    finally:

        bridge.cleanup()


if __name__ == "__main__":
    main()