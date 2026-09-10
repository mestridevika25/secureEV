import time

from simulation.carla_bridge import CarlaBridge

from digital_twin.vehicle_state import VehicleState
from digital_twin.vcu import VCU
from digital_twin.bms import BMS
from digital_twin.bcm import BCM
from digital_twin.mcu import MCU
from digital_twin.tcu import TCU
from digital_twin.digital_twin_manager import DigitalTwinManager


def main():

    print("\n======================================")
    print(" SecureEV - DIGITAL TWIN INTEGRATION")
    print("======================================\n", flush=True)

    bridge = None
    manager = None

    try:

        # =====================================================
        # 1. CONNECT TO CARLA
        # =====================================================

        print("[1] Connecting to CARLA...", flush=True)

        bridge = CarlaBridge()

        print("[2] CARLA connection successful.", flush=True)

        # =====================================================
        # 2. SPAWN EV
        # =====================================================

        print("[3] Spawning EV...", flush=True)

        bridge.spawn_vehicle()
        bridge.set_autopilot(False)

        print("[4] EV spawned successfully.", flush=True)

        # =====================================================
        # 3. CREATE SHARED VEHICLE STATE
        # =====================================================

        print("[5] Creating VehicleState...", flush=True)

        vehicle_state = VehicleState()

        # =====================================================
        # 4. CREATE VCU
        # =====================================================

        print("[6] Creating VCU...", flush=True)

        vcu = VCU(
            vehicle_state=vehicle_state,
            carla_bridge=bridge,
        )

        # =====================================================
        # 5. CREATE BMS
        # =====================================================

        print("[7] Creating BMS...", flush=True)

        bms = BMS(
            vehicle_state=vehicle_state,
            vcu=vcu,
        )

        # =====================================================
        # 6. CREATE BCM
        # =====================================================

        print("[8] Creating BCM...", flush=True)

        bcm = BCM(
            vehicle_state=vehicle_state,
        )

        # =====================================================
        # 7. CREATE MCU
        # =====================================================

        print("[9] Creating MCU...", flush=True)

        mcu = MCU(
            vehicle_state=vehicle_state,
            vcu=vcu,
        )

        # =====================================================
        # 8. CREATE TCU
        # =====================================================

        print("[10] Creating TCU...", flush=True)

        tcu = TCU(
            vehicle_state=vehicle_state,
            carla_bridge=bridge,
        )

        # =====================================================
        # 9. CREATE DIGITAL TWIN MANAGER
        # =====================================================

        print(
            "[11] Creating Digital Twin Manager...",
            flush=True
        )

        manager = DigitalTwinManager(
            vehicle_state=vehicle_state,
            tick_rate_hz=10.0,
        )

        # =====================================================
        # 10. REGISTER ALL ECUs
        # =====================================================

        print(
            "\n[12] Registering ECUs...",
            flush=True
        )

        manager.register_ecu(vcu)
        manager.register_ecu(bms)
        manager.register_ecu(bcm)
        manager.register_ecu(mcu)
        manager.register_ecu(tcu)

        print("\nRegistered ECUs:", flush=True)

        for ecu_id, ecu in manager.ecus.items():

            print(
                f"  - {ecu_id}: {ecu.status}",
                flush=True
            )

        # =====================================================
        # 11. INITIAL VEHICLE STATE
        # =====================================================

        print("\n======================================")
        print(" INITIAL VEHICLE STATE")
        print("======================================")

        print(
            f"Speed            : "
            f"{vehicle_state.speed_kmh:.2f} km/h"
        )

        print(
            f"Acceleration     : "
            f"{vehicle_state.acceleration:.3f} m/s²"
        )

        print(
            f"Battery SOC      : "
            f"{vehicle_state.battery_soc:.2f}%"
        )

        print(
            f"Battery Temp     : "
            f"{vehicle_state.battery_temp:.2f} °C"
        )

        print(
            f"Motor RPM        : "
            f"{vehicle_state.motor_rpm:.2f}"
        )

        print(
            f"Motor Temp       : "
            f"{vehicle_state.motor_temp:.2f} °C"
        )

        print(
            f"Doors Locked     : "
            f"{vehicle_state.doors_locked}"
        )

        print(
            f"Doors Open       : "
            f"{vehicle_state.doors_open}"
        )

        print(
            f"Reported GPS     : "
            f"{vehicle_state.reported_gps}"
        )

        # =====================================================
        # 12. BCM FUNCTION TEST
        # =====================================================

        print("\n======================================")
        print(" BCM FUNCTION TEST")
        print("======================================")

        print(
            "\n[BCM] Unlocking doors...",
            flush=True
        )

        bcm.unlock_doors()
        bcm.tick()

        print(
            f"Doors Locked = {vehicle_state.doors_locked} | "
            f"Doors Open = {vehicle_state.doors_open}"
        )

        print(
            "\n[BCM] Opening doors...",
            flush=True
        )

        bcm.open_doors()
        bcm.tick()

        print(
            f"Doors Locked = {vehicle_state.doors_locked} | "
            f"Doors Open = {vehicle_state.doors_open}"
        )

        print(
            "\n[BCM] Closing doors...",
            flush=True
        )

        bcm.close_doors()
        bcm.tick()

        print(
            f"Doors Locked = {vehicle_state.doors_locked} | "
            f"Doors Open = {vehicle_state.doors_open}"
        )

        print(
            "\n[BCM] Locking doors...",
            flush=True
        )

        bcm.lock_doors()
        bcm.tick()

        print(
            f"Doors Locked = {vehicle_state.doors_locked} | "
            f"Doors Open = {vehicle_state.doors_open}"
        )

        # =====================================================
        # 13. TCU INITIAL GPS TEST
        # =====================================================

        print("\n======================================")
        print(" TCU GPS TEST")
        print("======================================")

        print(
            "\n[TCU] Reading trusted GPS position...",
            flush=True
        )

        tcu.tick()

        gps = vehicle_state.reported_gps

        print(
            f"GPS Source       : {gps['source']}"
        )

        print(
            f"GPS Position     : "
            f"x={gps['x']:.2f}, "
            f"y={gps['y']:.2f}, "
            f"z={gps['z']:.2f}"
        )

        # =====================================================
        # 14. APPLY THROTTLE
        # =====================================================

        print("\n======================================")
        print(" COORDINATED VEHICLE SIMULATION")
        print("======================================")

        print(
            "\n[VCU] Applying throttle...",
            flush=True
        )

        vcu.apply_command(
            throttle=0.50,
            brake=0.0,
            steer=0.0,
        )

        print(
            "\nStarting five-ECU simulation loop...\n",
            flush=True
        )

        # =====================================================
        # 15. NORMAL DRIVING
        # =====================================================

        for i in range(20):

            telemetry = manager.tick()

            vcu_data = telemetry["VCU"]
            bms_data = telemetry["BMS"]
            bcm_data = telemetry["BCM"]
            mcu_data = telemetry["MCU"]
            tcu_data = telemetry["TCU"]

            gps = tcu_data["reported_gps"]

            print(
                f"[Tick {i + 1:02d}] "
                f"Speed={vcu_data['speed_kmh']:6.2f} km/h | "
                f"Accel={vcu_data['acceleration_mps2']:7.3f} m/s² | "
                f"SOC={bms_data['battery_soc']:6.2f}% | "
                f"BattTemp={bms_data['battery_temp']:5.2f}°C | "
                f"RPM={mcu_data['motor_rpm']:7.0f} | "
                f"MotorTemp={mcu_data['motor_temp']:5.2f}°C | "
                f"Locked={bcm_data['doors_locked']} | "
                f"GPS=({gps['x']:.2f}, {gps['y']:.2f})",
                flush=True
            )

            time.sleep(manager.tick_interval)

        # =====================================================
        # 16. EMERGENCY BRAKE
        # =====================================================

        print("\n======================================")
        print(" EMERGENCY BRAKE TEST")
        print("======================================")

        print(
            "\n[VCU] Applying emergency brake...",
            flush=True
        )

        vcu.emergency_brake()

        print()

        for i in range(8):

            telemetry = manager.tick()

            vcu_data = telemetry["VCU"]
            bms_data = telemetry["BMS"]
            mcu_data = telemetry["MCU"]
            tcu_data = telemetry["TCU"]

            gps = tcu_data["reported_gps"]

            print(
                f"[Brake {i + 1:02d}] "
                f"Speed={vcu_data['speed_kmh']:6.2f} km/h | "
                f"Accel={vcu_data['acceleration_mps2']:7.3f} m/s² | "
                f"SOC={bms_data['battery_soc']:6.2f}% | "
                f"RPM={mcu_data['motor_rpm']:7.0f} | "
                f"MotorTemp={mcu_data['motor_temp']:5.2f}°C | "
                f"GPS=({gps['x']:.2f}, {gps['y']:.2f})",
                flush=True
            )

            time.sleep(manager.tick_interval)

        # =====================================================
        # 17. FINAL VEHICLE STATE
        # =====================================================

        print("\n======================================")
        print(" FINAL VEHICLE STATE")
        print("======================================")

        print(
            f"Speed            : "
            f"{vehicle_state.speed_kmh:.2f} km/h"
        )

        print(
            f"Acceleration     : "
            f"{vehicle_state.acceleration:.3f} m/s²"
        )

        print(
            f"Battery SOC      : "
            f"{vehicle_state.battery_soc:.2f}%"
        )

        print(
            f"Battery Temp     : "
            f"{vehicle_state.battery_temp:.2f} °C"
        )

        print(
            f"Motor RPM        : "
            f"{vehicle_state.motor_rpm:.2f}"
        )

        print(
            f"Motor Temp       : "
            f"{vehicle_state.motor_temp:.2f} °C"
        )

        print(
            f"Doors Locked     : "
            f"{vehicle_state.doors_locked}"
        )

        print(
            f"Doors Open       : "
            f"{vehicle_state.doors_open}"
        )

        print(
            f"Reported GPS     : "
            f"{vehicle_state.reported_gps}"
        )

        # =====================================================
        # 18. MANAGER STATUS
        # =====================================================

        print("\n======================================")
        print(" DIGITAL TWIN MANAGER STATUS")
        print("======================================")

        status = manager.status()

        print(
            f"Running          : "
            f"{status['running']}"
        )

        print(
            f"Tick Count       : "
            f"{status['tick_count']}"
        )

        print(
            f"Tick Rate        : "
            f"{status['tick_rate_hz']} Hz"
        )

        print(
            f"ECU Count        : "
            f"{status['ecu_count']}"
        )

        print("\nECU Status:")

        for ecu_id, ecu_status in status["ecus"].items():

            print(
                f"  {ecu_id}: {ecu_status}"
            )

        # =====================================================
        # 19. ECU TELEMETRY
        # =====================================================

        print("\n======================================")
        print(" ECU TELEMETRY")
        print("======================================")

        print("\nVCU:")
        print(vcu.telemetry())

        print("\nBMS:")
        print(bms.telemetry())

        print("\nBCM:")
        print(bcm.telemetry())

        print("\nMCU:")
        print(mcu.telemetry())

        print("\nTCU:")
        print(tcu.telemetry())

        # =====================================================
        # 20. SUCCESS
        # =====================================================

        print("\n======================================")
        print(" PHASE 2 FIVE-ECU TEST PASSED")
        print("======================================\n")

    finally:

        if manager is not None:
            manager.stop()

        if bridge is not None:
            bridge.cleanup()


if __name__ == "__main__":
    main()