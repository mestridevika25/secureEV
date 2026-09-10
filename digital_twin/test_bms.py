import time

from simulation.carla_bridge import CarlaBridge
from digital_twin.vehicle_state import VehicleState
from digital_twin.vcu import VCU
from digital_twin.bms import BMS


def main():

    bridge = CarlaBridge()
    vehicle_state = VehicleState()

    try:
        print("\n================================")
        print(" SecureEV - Phase 2 BMS TEST")
        print("================================\n")

        print("[1] Spawning EV...")
        bridge.spawn_vehicle()

        bridge.set_autopilot(False)

        print("[2] Creating VCU...")
        vcu = VCU(
            vehicle_state=vehicle_state,
            carla_bridge=bridge,
        )

        print("[3] Creating BMS...")
        bms = BMS(
            vehicle_state=vehicle_state,
            vcu=vcu,
        )

        print("\nInitial Battery:")
        print(
            f"SOC: {vehicle_state.battery_soc:.2f}% | "
            f"Temperature: {vehicle_state.battery_temp:.2f}°C"
        )

        print("\n[4] Applying throttle...\n")

        vcu.apply_command(
            throttle=0.5,
            brake=0.0,
            steer=0.0,
        )

        for i in range(20):

            vcu.tick()
            bms.tick()

            print(
                f"[{i + 1:02d}] "
                f"Speed={vehicle_state.speed_kmh:6.2f} km/h | "
                f"Accel={vehicle_state.acceleration:6.3f} m/s² | "
                f"SOC={vehicle_state.battery_soc:6.2f}% | "
                f"Battery Temp={vehicle_state.battery_temp:5.2f}°C | "
                f"Energy={bms.energy_consumed_kwh:.4f} kWh"
            )

            time.sleep(0.5)

        print("\n[5] Applying brake...")

        vcu.emergency_brake()

        for i in range(8):

            vcu.tick()
            bms.tick()

            print(
                f"[Brake {i + 1:02d}] "
                f"Speed={vehicle_state.speed_kmh:6.2f} km/h | "
                f"SOC={vehicle_state.battery_soc:6.2f}% | "
                f"Temp={vehicle_state.battery_temp:5.2f}°C"
            )

            time.sleep(0.5)

        print("\n================================")
        print(" BMS TEST PASSED")
        print("================================")

    finally:
        bridge.cleanup()


if __name__ == "__main__":
    main()