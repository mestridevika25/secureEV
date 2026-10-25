"""
SecureEV - Phase 3B Integrated Manual Driving

Development/test interface for the completed Phase 3 vehicle subsystems.

Controls
--------
W / UP       Accelerate (manual mode)
S / DOWN     Brake (manual mode)
A / LEFT     Steer left (manual mode)
D / RIGHT    Steer right (manual mode)
SPACE        Emergency brake

1            Lock doors
2            Unlock doors
3            Open doors
4            Close doors

C            Change camera
M            Toggle Manual / Autonomous mode
G            Connect / disconnect charger
T            Start charging
X            Stop charging
U            Run a valid simulated OTA update
R            Reset vehicle
ESC          Exit

Architecture
------------
Keyboard
    -> Manual / Autonomous control
    -> VCU
    -> CarlaBridge
    -> CARLA

Digital Twin
------------
VCU, BMS, BCM, MCU, TCU, ACU, CHG, CAM, OTA

Notes
-----
This file is intentionally separate from the known-good
simulation/manual_drive.py so Phase 3B can be tested without risking the
Phase 2.5 baseline.

No NumPy is used.
"""

from __future__ import annotations

import time
import os

import pygame

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


WINDOW_WIDTH = 900
WINDOW_HEIGHT = 600

CAMERA_WIDTH = 640
CAMERA_HEIGHT = 360

TICK_RATE = 20.0
MAX_MANUAL_THROTTLE = 0.60
AUTONOMOUS_TARGET_SPEED = 20.0
AUTONOMOUS_MAX_THROTTLE = 0.60

THROTTLE_RESPONSE = 1.8
BRAKE_RESPONSE = 5.0
STEER_RESPONSE = 4.0
STEER_RETURN = 6.0

CAMERA_VIEWS = ["front", "rear", "left", "right"]

BG = (10, 15, 22)
PANEL = (20, 28, 38)
BORDER = (45, 65, 80)
TEXT = (235, 240, 245)
ACCENT = (70, 220, 170)
DANGER = (240, 80, 80)
WARNING = (245, 190, 80)


def approach(current: float, target: float, amount: float) -> float:
    if current < target:
        return min(current + amount, target)
    if current > target:
        return max(current - amount, target)
    return current


def draw_text(screen, font, text, x, y, color=TEXT) -> None:
    surface = font.render(str(text), True, color)
    screen.blit(surface, (x, y))


def draw_panel(screen, rect, title, heading_font) -> None:
    pygame.draw.rect(screen, PANEL, rect, border_radius=8)
    pygame.draw.rect(screen, BORDER, rect, width=1, border_radius=8)
    x, y, _, _ = rect
    draw_text(screen, heading_font, title, x + 12, y + 8)


def create_camera_surface(raw_frame, width: int, height: int):
    """Convert CARLA BGRA bytes directly to a Pygame surface."""
    if raw_frame is None:
        return None

    expected_size = width * height * 4
    if len(raw_frame) != expected_size:
        return None

    try:
        return pygame.image.frombuffer(
            raw_frame,
            (width, height),
            "BGRA",
        )
    except (ValueError, pygame.error):
        return None


def next_demo_version(current: str) -> str:
    """Return a simple deterministic next patch version for the demo OTA."""
    try:
        parts = [int(part) for part in str(current).split(".")]
        if len(parts) != 3:
            raise ValueError
        parts[2] += 1
        return ".".join(str(part) for part in parts)
    except (TypeError, ValueError):
        return "1.0.1"


def safe_status_for_vehicle(state: VehicleState) -> str:
    if state.vehicle_disabled_flag:
        return "DISABLED"
    if state.charging_state == "charging":
        return "CHARGING"
    if state.doors_open:
        return "DOORS OPEN"
    if state.autonomous_mode:
        return "AUTONOMOUS"
    return "MANUAL"


def main() -> None:
    print("\n======================================", flush=True)
    print(" SecureEV - PHASE 3B MANUAL DRIVE", flush=True)
    print("======================================\n", flush=True)

    bridge = None
    manager = None
    pygame_initialized = False

    try:
        # -----------------------------------------------------
        # Pygame
        # -----------------------------------------------------
        print("[1] Starting SecureEV controller...", flush=True)
        pygame.init()
        pygame_initialized = True

        screen = pygame.display.set_mode(
            (WINDOW_WIDTH, WINDOW_HEIGHT),
            pygame.RESIZABLE,
        )
        pygame.display.set_caption("SecureEV - Phase 3B")
        clock = pygame.time.Clock()

        title_font = pygame.font.SysFont("Arial", 24, bold=True)
        heading_font = pygame.font.SysFont("Arial", 17, bold=True)
        font = pygame.font.SysFont("Arial", 14)
        small_font = pygame.font.SysFont("Arial", 12)

        # -----------------------------------------------------
        # CARLA
        # -----------------------------------------------------
        print("[2] Connecting to CARLA...", flush=True)
        bridge = CarlaBridge()

        print("[3] Spawning EV...", flush=True)
        bridge.spawn_vehicle()
        bridge.set_autopilot(False)
        bridge.attach_rgb_camera(
            width=CAMERA_WIDTH,
            height=CAMERA_HEIGHT,
            fov=90.0,
        )
        bridge.follow_vehicle()

        # -----------------------------------------------------
        # Vehicle state + modules
        # -----------------------------------------------------
        print("[4] Creating VehicleState and modules...", flush=True)
        state = VehicleState()

        vcu = VCU(state, bridge)
        charging = ChargingController(state, charging_power_kw=11.0)
        bms = BMS(state, vcu=vcu, charging_controller=charging)
        bcm = BCM(state)
        mcu = MCU(state, vcu=vcu)
        tcu = TCU(state, bridge)
        acu = ACU(state)
        acu.max_throttle = AUTONOMOUS_MAX_THROTTLE
        camera = CameraModule(state, bridge)
        firmware_key = os.getenv("SECUREEV_FIRMWARE_SIGNING_KEY")
        firmware_checker = IntegrityChecker(
            firmware_key.encode("utf-8") if firmware_key else None
        )
        ota = OTAManager(state, firmware_checker)

        manager = DigitalTwinManager(
            vehicle_state=state,
            tick_rate_hz=TICK_RATE,
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

        print("\nRegistered modules:", flush=True)
        for ecu_id, ecu in manager.ecus.items():
            print(f"  - {ecu_id}: {ecu.status}", flush=True)

        # -----------------------------------------------------
        # Control state
        # -----------------------------------------------------
        throttle = 0.0
        brake = 0.0
        steer = 0.0

        camera_index = 0
        current_camera = "front"
        status_message = "Phase 3B ready"
        running = True

        print("\nControls:", flush=True)
        print("W / UP   Accelerate | S / DOWN   Brake", flush=True)
        print("A / LEFT Steer      | D / RIGHT  Steer", flush=True)
        print("SPACE Emergency Brake | M Manual/Auto", flush=True)
        print("1-4 Doors | C Camera | G Charger | T Start | X Stop", flush=True)
        print("U OTA update | R Reset | ESC Exit\n", flush=True)

        # -----------------------------------------------------
        # Main loop
        # -----------------------------------------------------
        while running:
            dt = clock.tick(int(TICK_RATE)) / 1000.0
            dt = max(0.001, min(dt, 0.1))

            # ---------------------------------------------
            # Events
            # ---------------------------------------------
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                    continue

                if event.type != pygame.KEYDOWN:
                    continue

                key = event.key

                if key == pygame.K_ESCAPE:
                    running = False

                elif key == pygame.K_SPACE:
                    throttle = 0.0
                    brake = 1.0
                    state.autonomous_mode = False
                    acu.disable_autonomous_mode()
                    try:
                        vcu.emergency_brake()
                        status_message = "EMERGENCY BRAKE"
                    except RuntimeError as exc:
                        status_message = str(exc)

                elif key == pygame.K_1:
                    try:
                        bcm.lock_doors()
                        status_message = "Doors LOCKED"
                    except RuntimeError as exc:
                        status_message = str(exc)

                elif key == pygame.K_2:
                    try:
                        bcm.unlock_doors()
                        status_message = "Doors UNLOCKED"
                    except RuntimeError as exc:
                        status_message = str(exc)

                elif key == pygame.K_3:
                    if state.speed_kmh > 1.0:
                        status_message = "Cannot open doors while moving"
                    else:
                        try:
                            bcm.open_doors()
                            status_message = "Doors OPEN"
                        except RuntimeError as exc:
                            status_message = str(exc)

                elif key == pygame.K_4:
                    try:
                        bcm.close_doors()
                        status_message = "Doors CLOSED"
                    except RuntimeError as exc:
                        status_message = str(exc)

                elif key == pygame.K_c:
                    camera_index = (camera_index + 1) % len(CAMERA_VIEWS)
                    current_camera = CAMERA_VIEWS[camera_index]
                    try:
                        bridge.set_camera_view(current_camera)
                        status_message = f"Camera: {current_camera.upper()}"
                    except RuntimeError as exc:
                        status_message = str(exc)

                elif key == pygame.K_m:
                    try:
                        if state.autonomous_mode:
                            acu.disable_autonomous_mode()
                            status_message = "Mode: MANUAL"
                        elif state.vehicle_disabled_flag:
                            status_message = "Autonomous mode blocked: vehicle disabled"
                        elif state.doors_open:
                            status_message = "Autonomous mode blocked: doors open"
                        elif state.charging_state == "charging":
                            status_message = "Autonomous mode blocked: charging"
                        else:
                            acu.enable_autonomous_mode(AUTONOMOUS_TARGET_SPEED)
                            status_message = (
                                f"Mode: AUTONOMOUS @ {AUTONOMOUS_TARGET_SPEED:.0f} km/h"
                            )
                    except RuntimeError as exc:
                        status_message = str(exc)

                elif key == pygame.K_g:
                    try:
                        if charging.is_charging():
                            status_message = "Stop charging first"
                        elif charging.charger_connected:
                            charging.disconnect_charger()
                            status_message = "Charger DISCONNECTED"
                        else:
                            charging.connect_charger()
                            status_message = "Charger CONNECTED"
                    except RuntimeError as exc:
                        status_message = str(exc)

                elif key == pygame.K_t:
                    try:
                        if state.speed_kmh > 1.0:
                            status_message = "Stop vehicle before charging"
                        elif state.autonomous_mode:
                            status_message = "Switch to MANUAL before charging"
                        elif state.doors_open:
                            status_message = "Close doors before charging"
                        else:
                            charging.start_charging()
                            status_message = "Charging STARTED"
                    except RuntimeError as exc:
                        status_message = str(exc)

                elif key == pygame.K_x:
                    try:
                        charging.stop_charging()
                        status_message = "Charging STOPPED"
                    except RuntimeError as exc:
                        status_message = str(exc)

                elif key == pygame.K_u:
                    try:
                        if state.speed_kmh > 1.0:
                            status_message = "Stop vehicle before OTA update"
                        elif state.charging_state == "charging":
                            status_message = "Stop charging before OTA update"
                        else:
                            version = next_demo_version(state.firmware_version)
                            package = (
                                f"SecureEV simulated firmware package {version}".encode()
                            )
                            package_hash = ota.stage_update(
                                version=version,
                                package_data=package,
                                signature=firmware_checker.sign_firmware_package(package),
                            )
                            success = ota.install_update()
                            if success:
                                status_message = (
                                    f"OTA OK: {version} | SHA256 {package_hash[:10]}..."
                                )
                            else:
                                status_message = "OTA REJECTED"
                    except RuntimeError as exc:
                        status_message = str(exc)

                elif key == pygame.K_r:
                    throttle = 0.0
                    brake = 0.0
                    steer = 0.0
                    try:
                        acu.disable_autonomous_mode()
                    except RuntimeError:
                        pass
                    try:
                        charging.stop_charging()
                    except RuntimeError:
                        pass
                    try:
                        bridge.reset_vehicle()
                        status_message = "Vehicle RESET"
                    except RuntimeError as exc:
                        status_message = str(exc)

            # ---------------------------------------------
            # Control calculation
            # ---------------------------------------------
            controls_inhibited = (
                state.doors_open
                or state.vehicle_disabled_flag
                or state.charging_state == "charging"
            )

            if state.autonomous_mode:
                # ACU has already updated planned_* in manager.tick() from the
                # previous cycle. We keep the control deliberately capped.
                throttle_target = state.planned_throttle
                brake_target = state.planned_brake
                steer_target = state.planned_steer

                if controls_inhibited:
                    throttle_target = 0.0
                    brake_target = 1.0
                    steer_target = 0.0

                throttle = approach(
                    throttle,
                    max(0.0, min(AUTONOMOUS_MAX_THROTTLE, throttle_target)),
                    THROTTLE_RESPONSE * dt,
                )
                brake = approach(
                    brake,
                    max(0.0, min(1.0, brake_target)),
                    BRAKE_RESPONSE * dt,
                )
                steer = approach(
                    steer,
                    max(-1.0, min(1.0, steer_target)),
                    STEER_RESPONSE * dt,
                )

            else:
                keys = pygame.key.get_pressed()

                throttle_target = 0.0
                if keys[pygame.K_w] or keys[pygame.K_UP]:
                    throttle_target = MAX_MANUAL_THROTTLE
                if controls_inhibited:
                    throttle_target = 0.0

                brake_target = 1.0 if (
                    keys[pygame.K_s]
                    or keys[pygame.K_DOWN]
                    or keys[pygame.K_SPACE]
                ) else 0.0
                if controls_inhibited:
                    brake_target = 1.0

                steer_target = 0.0
                if keys[pygame.K_a] or keys[pygame.K_LEFT]:
                    steer_target = -1.0
                elif keys[pygame.K_d] or keys[pygame.K_RIGHT]:
                    steer_target = 1.0

                throttle = approach(
                    throttle,
                    throttle_target,
                    THROTTLE_RESPONSE * dt,
                )
                brake = approach(
                    brake,
                    brake_target,
                    BRAKE_RESPONSE * dt,
                )
                steer = approach(
                    steer,
                    steer_target,
                    (
                        STEER_RESPONSE
                        if steer_target != 0.0
                        else STEER_RETURN
                    ) * dt,
                )

            # ---------------------------------------------
            # VCU / Digital Twin
            # ---------------------------------------------
            try:
                vcu.apply_command(
                    throttle=throttle,
                    brake=brake,
                    steer=steer,
                )
            except RuntimeError as exc:
                throttle = 0.0
                brake = 1.0
                steer = 0.0
                status_message = str(exc)

            try:
                manager.tick()
            except Exception as exc:
                status_message = f"Digital Twin Error: {exc}"

            try:
                bridge.follow_vehicle()
            except Exception:
                pass

            frame = create_camera_surface(
                camera.get_frame(),
                CAMERA_WIDTH,
                CAMERA_HEIGHT,
            )

            # ---------------------------------------------
            # Draw
            # ---------------------------------------------
            screen.fill(BG)

            pygame.draw.rect(
                screen,
                (18, 28, 40),
                (0, 0, WINDOW_WIDTH, 60),
            )
            draw_text(screen, title_font, "SECUREEV", 18, 15, ACCENT)
            draw_text(screen, font, "PHASE 3B • CONNECTED EV", 160, 21)
            draw_text(
                screen,
                small_font,
                f"CARLA | {current_camera.upper()}",
                745,
                22,
                ACCENT,
            )

            # Camera
            pygame.draw.rect(
                screen,
                (15, 22, 30),
                (15, 75, CAMERA_WIDTH, CAMERA_HEIGHT),
            )
            if frame is not None:
                screen.blit(frame, (15, 75))
            else:
                draw_text(screen, font, "Waiting for camera...", 230, 245)

            # Control panel
            draw_panel(screen, (670, 75, 215, 220), "CONTROLS", heading_font)
            control_lines = [
                "W/↑  Accelerate",
                "S/↓  Brake",
                "A/←  Left",
                "D/→  Right",
                "SPACE Emergency",
                "M    Manual/Auto",
                "C    Camera",
                "R    Reset",
                "ESC  Exit",
            ]
            y = 108
            for line in control_lines:
                draw_text(screen, small_font, line, 685, y)
                y += 21

            # Vehicle functions
            draw_panel(
                screen,
                (670, 310, 215, 150),
                "EV FUNCTIONS",
                heading_font,
            )
            function_lines = [
                "1-4  Doors",
                "G    Charger",
                "T    Start charge",
                "X    Stop charge",
                "U    OTA update",
            ]
            y = 344
            for line in function_lines:
                draw_text(screen, small_font, line, 685, y)
                y += 22

            # Telemetry
            draw_panel(screen, (15, 450, 430, 135), "LIVE TELEMETRY", heading_font)
            gps = state.reported_gps
            gps_text = (
                f"{gps['x']:.1f}, {gps['y']:.1f}"
                if gps
                else "N/A"
            )
            left = [
                ("Speed", f"{state.speed_kmh:.1f} km/h"),
                ("Battery", f"{state.battery_soc:.1f}%"),
                ("Batt Temp", f"{state.battery_temp:.1f} C"),
                ("Motor RPM", f"{state.motor_rpm:.0f}"),
            ]
            right = [
                ("Motor Temp", f"{state.motor_temp:.1f} C"),
                ("GPS", gps_text),
                ("Mode", safe_status_for_vehicle(state)),
                ("Firmware", state.firmware_version),
            ]
            for i, (label, value) in enumerate(left):
                y = 480 + i * 24
                draw_text(screen, small_font, f"{label}:", 30, y)
                draw_text(screen, small_font, value, 125, y, ACCENT)
            for i, (label, value) in enumerate(right):
                y = 480 + i * 24
                draw_text(screen, small_font, f"{label}:", 225, y)
                draw_text(screen, small_font, value, 320, y, ACCENT)

            # ECU status
            draw_panel(screen, (460, 450, 425, 135), "VEHICLE / ECU STATUS", heading_font)
            modules = [
                ("VCU", vcu.status),
                ("BMS", bms.status),
                ("BCM", bcm.status),
                ("MCU", mcu.status),
                ("TCU", tcu.status),
                ("ACU", acu.status),
                ("CHG", charging.status),
                ("CAM", camera.status),
                ("OTA", ota.status),
            ]
            for i, (name, status) in enumerate(modules):
                row = i // 5
                col = i % 5
                x = 472 + col * 80
                y = 482 + row * 27
                color = ACCENT if status == "ONLINE" else DANGER
                draw_text(screen, small_font, name, x, y)
                draw_text(screen, small_font, status, x, y + 13, color)

            draw_text(
                screen,
                small_font,
                f"Throttle:{throttle:.2f}",
                472,
                540,
            )
            draw_text(
                screen,
                small_font,
                f"Brake:{brake:.2f}",
                565,
                540,
            )
            draw_text(
                screen,
                small_font,
                f"Steer:{steer:+.2f}",
                650,
                540,
            )
            charge_text = state.charging_state.upper()
            draw_text(
                screen,
                small_font,
                f"Charge:{charge_text}",
                730,
                540,
                WARNING if charge_text == "CHARGING" else TEXT,
            )

            # Status bar
            pygame.draw.rect(screen, (15, 42, 39), (15, 590, 870, 10))
            # Keep message visible near the bottom without exceeding the window.
            if status_message:
                # Render on top of the status area so the UI still works if the
                # window height is exactly the configured 600 pixels.
                overlay = font.render(status_message, True, ACCENT)
                screen.blit(overlay, (25, 570))

            pygame.display.flip()

        # Safe stop
        print("\nStopping vehicle safely...", flush=True)
        try:
            acu.disable_autonomous_mode()
        except Exception:
            pass
        try:
            charging.stop_charging()
        except Exception:
            pass
        try:
            vcu.apply_command(throttle=0.0, brake=1.0, steer=0.0)
            time.sleep(0.3)
        except Exception:
            pass

    finally:
        if manager is not None:
            try:
                manager.stop()
            except Exception:
                pass

        if bridge is not None:
            bridge.cleanup()

        if pygame_initialized:
            pygame.quit()

        print("Phase 3B session ended.", flush=True)


if __name__ == "__main__":
    main()
