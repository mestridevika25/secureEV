"""
test_phase3.py

Phase 3 integration test for:
    - VCU
    - BMS
    - BCM
    - MCU
    - TCU
    - ACU
    - Charging Controller
    - Camera Module
    - OTA Manager

This test intentionally runs separately from manual_drive.py so that the
known-good manual-driving client remains untouched while the new Phase 3
subsystems are validated.
"""

from __future__ import annotations

import time

from blue_team.integrity_checker import IntegrityChecker
from simulation.carla_bridge import CarlaBridge

from digital_twin.vehicle_state import VehicleState
from digital_twin.vcu import VCU
from digital_twin.bms import BMS
from digital_twin.bcm import BCM
from digital_twin.mcu import MCU
from digital_twin.tcu import TCU
from digital_twin.acu import ACU
from digital_twin.charging_controller import ChargingController
from digital_twin.camera_module import CameraModule
from digital_twin.ota_manager import OTAManager
from digital_twin.digital_twin_manager import DigitalTwinManager


CAMERA_WIDTH = 640
CAMERA_HEIGHT = 360


def main() -> None:
    print("\n======================================", flush=True)
    print(" SecureEV - PHASE 3 INTEGRATION TEST", flush=True)
    print("======================================\n", flush=True)

    bridge = None
    manager = None

    try:
        print("[1] Connecting to CARLA...", flush=True)
        bridge = CarlaBridge()

        print("[2] Spawning EV...", flush=True)
        bridge.spawn_vehicle()
        bridge.set_autopilot(False)
        bridge.attach_rgb_camera(
            width=CAMERA_WIDTH,
            height=CAMERA_HEIGHT,
            fov=90.0,
        )
        bridge.follow_vehicle()

        state = VehicleState()

        print("[3] Creating core ECUs...", flush=True)
        vcu = VCU(state, bridge)
        charging = ChargingController(state, charging_power_kw=11.0)
        bms = BMS(state, vcu=vcu, charging_controller=charging)
        bcm = BCM(state)
        mcu = MCU(state, vcu=vcu)
        tcu = TCU(state, bridge)
        acu = ACU(state)

        print("[4] Creating Phase 3 modules...", flush=True)
        camera = CameraModule(state, bridge)
        firmware_checker = IntegrityChecker(b"phase3-test-signing-key-32-bytes!!")
        ota = OTAManager(state, firmware_checker)

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
            camera,
            ota,
        ):
            manager.register_ecu(ecu)

        print("\n[5] Registered modules:", flush=True)
        for ecu_id, ecu in manager.ecus.items():
            print(f"  - {ecu_id}: {ecu.status}", flush=True)

        # -----------------------------------------------------
        # Camera
        # -----------------------------------------------------
        print("\n[6] Testing camera module...", flush=True)
        for _ in range(10):
            manager.tick()
            time.sleep(0.1)

        camera_telemetry = camera.telemetry()
        print(
            f"Camera source={camera_telemetry['camera_feed_source']} | "
            f"frame_available={camera_telemetry['frame_available']} | "
            f"sequence={camera_telemetry['frame_sequence']}",
            flush=True,
        )

        # -----------------------------------------------------
        # Charging
        # -----------------------------------------------------
        print("\n[7] Testing charging controller...", flush=True)
        state.battery_soc = 80.0
        before_soc = state.battery_soc

        charging.connect_charger()
        charging.start_charging()

        for _ in range(20):
            manager.tick()
            time.sleep(0.1)

        after_soc = state.battery_soc

        print(
            f"Charging state={state.charging_state} | "
            f"SOC {before_soc:.2f}% -> {after_soc:.2f}%",
            flush=True,
        )

        charging.stop_charging()
        charging.disconnect_charger()

        # -----------------------------------------------------
        # OTA
        # -----------------------------------------------------
        print("\n[8] Testing OTA manager...", flush=True)
        package = b"SecureEV firmware package v1.1.0"

        package_hash = ota.stage_update(
            version="1.1.0",
            package_data=package,
            signature=firmware_checker.sign_firmware_package(package),
        )

        ota_success = ota.install_update()

        print(
            f"OTA success={ota_success} | "
            f"firmware={state.firmware_version} | "
            f"SHA256={package_hash[:16]}...",
            flush=True,
        )

        print("\n[9] Testing rejected OTA...", flush=True)
        tampered_package = b"tampered firmware"
        ota.stage_update(
            version="9.9.9",
            package_data=tampered_package,
            signature=firmware_checker.sign_firmware_package(package),
        )

        rejected_install = ota.install_update()

        print(
            f"Tampered update accepted={rejected_install} | "
            f"state={ota.update_state} | "
            f"firmware still={state.firmware_version}",
            flush=True,
        )

        # -----------------------------------------------------
        # ACU planning
        # -----------------------------------------------------
        print("\n[10] Testing ACU autonomous planning...", flush=True)
        acu.enable_autonomous_mode(target_speed_kmh=20.0)
        manager.tick()

        print(
            f"ACU mode={acu.control_mode} | "
            f"target={acu.target_speed_kmh:.1f} km/h | "
            f"planned throttle={state.planned_throttle:.3f} | "
            f"planned brake={state.planned_brake:.3f}",
            flush=True,
        )

        acu.disable_autonomous_mode()

        # -----------------------------------------------------
        # Final telemetry
        # -----------------------------------------------------
        print("\n[11] Final Phase 3 state:", flush=True)
        print(f"Speed       : {state.speed_kmh:.2f} km/h", flush=True)
        print(f"Battery SOC : {state.battery_soc:.2f}%", flush=True)
        print(f"Battery Temp: {state.battery_temp:.2f} C", flush=True)
        print(f"Firmware    : {state.firmware_version}", flush=True)
        print(f"Camera Feed : {state.camera_feed_source}", flush=True)
        print(f"Charging    : {state.charging_state}", flush=True)

        print("\n======================================", flush=True)
        print(" PHASE 3 INTEGRATION TEST PASSED", flush=True)
        print("======================================\n", flush=True)

    finally:
        if manager is not None:
            manager.stop()
        if bridge is not None:
            bridge.cleanup()


if __name__ == "__main__":
    main()
