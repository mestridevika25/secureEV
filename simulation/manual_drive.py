"""
SecureEV - Manual Driving Mode

Controls
--------
W / UP       Accelerate
S / DOWN     Brake
A / LEFT     Steer left
D / RIGHT    Steer right
SPACE        Emergency brake

1            Lock doors
2            Unlock doors
3            Open doors
4            Close doors

C            Change camera
R            Reset vehicle
ESC          Exit

Architecture
------------
Keyboard
    ↓
Manual Controller
    ↓
VCU
    ↓
CarlaBridge
    ↓
CARLA

Digital Twin
------------
VCU
BMS
BCM
MCU
TCU
"""

from __future__ import annotations

import time

import pygame

from simulation.carla_bridge import CarlaBridge

from digital_twin.vehicle_state import VehicleState
from digital_twin.vcu import VCU
from digital_twin.bms import BMS
from digital_twin.bcm import BCM
from digital_twin.mcu import MCU
from digital_twin.tcu import TCU

from digital_twin.digital_twin_manager import (
    DigitalTwinManager
)


# =============================================================
# DISPLAY
# =============================================================

WINDOW_WIDTH = 900
WINDOW_HEIGHT = 600

CAMERA_WIDTH = 640
CAMERA_HEIGHT = 360

TICK_RATE = 20.0


# =============================================================
# VEHICLE CONTROL
# =============================================================

MAX_THROTTLE = 0.60

THROTTLE_RESPONSE = 1.8
BRAKE_RESPONSE = 5.0

STEER_RESPONSE = 4.0
STEER_RETURN = 6.0


# =============================================================
# CAMERA
# =============================================================

CAMERA_VIEWS = [
    "front",
    "rear",
    "left",
    "right"
]


# =============================================================
# HELPERS
# =============================================================

def approach(
    current: float,
    target: float,
    amount: float
) -> float:

    if current < target:

        return min(
            current + amount,
            target
        )

    if current > target:

        return max(
            current - amount,
            target
        )

    return current


def draw_text(
    screen,
    font,
    text,
    x,
    y,
    color=(235, 240, 245)
):

    surface = font.render(
        str(text),
        True,
        color
    )

    screen.blit(
        surface,
        (x, y)
    )


def draw_panel(
    screen,
    rect,
    title,
    heading_font
):

    pygame.draw.rect(
        screen,
        (20, 28, 38),
        rect,
        border_radius=8
    )

    pygame.draw.rect(
        screen,
        (45, 65, 80),
        rect,
        width=1,
        border_radius=8
    )

    x, y, _, _ = rect

    draw_text(
        screen,
        heading_font,
        title,
        x + 12,
        y + 10
    )


def create_camera_surface(
    raw_frame,
    width,
    height
):
    """
    Convert CARLA BGRA camera data directly into
    a Pygame surface.

    No NumPy required.
    """

    if raw_frame is None:
        return None

    expected_size = (
        width
        * height
        * 4
    )

    if len(raw_frame) != expected_size:
        return None

    try:

        # Pygame can interpret the CARLA BGRA buffer
        # directly, avoiding NumPy/OpenBLAS.
        surface = pygame.image.frombuffer(
            raw_frame,
            (width, height),
            "BGRA"
        )

        return surface

    except (ValueError, pygame.error):

        return None


# =============================================================
# MAIN
# =============================================================

def main():

    print(
        "\n======================================",
        flush=True
    )

    print(
        " SecureEV - MANUAL DRIVING MODE",
        flush=True
    )

    print(
        "======================================\n",
        flush=True
    )

    bridge = None
    manager = None

    pygame_initialized = False

    try:

        # =====================================================
        # 1. PYGAME
        # =====================================================

        print(
            "[1] Starting SecureEV controller...",
            flush=True
        )

        pygame.init()

        pygame_initialized = True

        screen = pygame.display.set_mode(
            (
                WINDOW_WIDTH,
                WINDOW_HEIGHT
            ),
            pygame.RESIZABLE
        )

        pygame.display.set_caption(
            "SecureEV - Manual Driving"
        )

        clock = pygame.time.Clock()

        title_font = pygame.font.SysFont(
            "Arial",
            24,
            bold=True
        )

        heading_font = pygame.font.SysFont(
            "Arial",
            18,
            bold=True
        )

        font = pygame.font.SysFont(
            "Arial",
            15
        )

        small_font = pygame.font.SysFont(
            "Arial",
            13
        )

        # =====================================================
        # 2. CONNECT TO CARLA
        # =====================================================

        print(
            "[2] Connecting to CARLA...",
            flush=True
        )

        bridge = CarlaBridge()

        # =====================================================
        # 3. SPAWN VEHICLE
        # =====================================================

        print(
            "[3] Spawning EV...",
            flush=True
        )

        bridge.spawn_vehicle()

        bridge.set_autopilot(
            False
        )

        print(
            "[4] EV spawned successfully.",
            flush=True
        )

        # =====================================================
        # 4. CAMERA
        # =====================================================

        print(
            "[5] Attaching driving camera...",
            flush=True
        )

        bridge.attach_rgb_camera(
            width=CAMERA_WIDTH,
            height=CAMERA_HEIGHT,
            fov=90.0
        )

        # =====================================================
        # 5. VEHICLE STATE
        # =====================================================

        print(
            "[6] Creating VehicleState...",
            flush=True
        )

        vehicle_state = VehicleState()

        # =====================================================
        # 6. VCU
        # =====================================================

        print(
            "[7] Creating VCU...",
            flush=True
        )

        vcu = VCU(
            vehicle_state=vehicle_state,
            carla_bridge=bridge
        )

        # =====================================================
        # 7. BMS
        # =====================================================

        print(
            "[8] Creating BMS...",
            flush=True
        )

        bms = BMS(
            vehicle_state=vehicle_state,
            vcu=vcu
        )

        # =====================================================
        # 8. BCM
        # =====================================================

        print(
            "[9] Creating BCM...",
            flush=True
        )

        bcm = BCM(
            vehicle_state=vehicle_state
        )

        # =====================================================
        # 9. MCU
        # =====================================================

        print(
            "[10] Creating MCU...",
            flush=True
        )

        mcu = MCU(
            vehicle_state=vehicle_state,
            vcu=vcu
        )

        # =====================================================
        # 10. TCU
        # =====================================================

        print(
            "[11] Creating TCU...",
            flush=True
        )

        tcu = TCU(
            vehicle_state=vehicle_state,
            carla_bridge=bridge
        )

        # =====================================================
        # 11. DIGITAL TWIN MANAGER
        # =====================================================

        print(
            "[12] Creating Digital Twin Manager...",
            flush=True
        )

        manager = DigitalTwinManager(
            vehicle_state=vehicle_state,
            tick_rate_hz=TICK_RATE
        )

        manager.register_ecu(vcu)
        manager.register_ecu(bms)
        manager.register_ecu(bcm)
        manager.register_ecu(mcu)
        manager.register_ecu(tcu)

        print(
            "\nRegistered ECUs:",
            flush=True
        )

        for ecu_id, ecu in manager.ecus.items():

            print(
                f"  - {ecu_id}: {ecu.status}",
                flush=True
            )

        # =====================================================
        # 12. INITIAL CAMERA POSITION
        # =====================================================

        bridge.follow_vehicle()

        # =====================================================
        # CONTROL STATE
        # =====================================================

        throttle = 0.0
        brake = 0.0
        steer = 0.0

        camera_index = 0
        current_camera = "front"

        status_message = (
            "Manual driving ready"
        )

        running = True

        # =====================================================
        # READY
        # =====================================================

        print(
            "\n======================================",
            flush=True
        )

        print(
            " MANUAL CONTROL READY",
            flush=True
        )

        print(
            "======================================",
            flush=True
        )

        print(
            "W / UP       Accelerate",
            flush=True
        )

        print(
            "S / DOWN     Brake",
            flush=True
        )

        print(
            "A / LEFT     Steer Left",
            flush=True
        )

        print(
            "D / RIGHT    Steer Right",
            flush=True
        )

        print(
            "SPACE        Emergency Brake",
            flush=True
        )

        print(
            "1            Lock Doors",
            flush=True
        )

        print(
            "2            Unlock Doors",
            flush=True
        )

        print(
            "3            Open Doors",
            flush=True
        )

        print(
            "4            Close Doors",
            flush=True
        )

        print(
            "C            Change Camera",
            flush=True
        )

        print(
            "R            Reset Vehicle",
            flush=True
        )

        print(
            "ESC          Exit\n",
            flush=True
        )

        # =====================================================
        # MAIN LOOP
        # =====================================================

        while running:

            dt = (
                clock.tick(
                    int(TICK_RATE)
                ) / 1000.0
            )

            dt = max(
                0.001,
                min(dt, 0.1)
            )

            # -------------------------------------------------
            # EVENTS
            # -------------------------------------------------

            for event in pygame.event.get():

                if event.type == pygame.QUIT:

                    running = False

                elif event.type == pygame.KEYDOWN:

                    # -----------------------------------------
                    # EXIT
                    # -----------------------------------------

                    if event.key == pygame.K_ESCAPE:

                        running = False

                    # -----------------------------------------
                    # EMERGENCY BRAKE
                    # -----------------------------------------

                    elif event.key == pygame.K_SPACE:

                        throttle = 0.0
                        brake = 1.0

                        try:

                            vcu.emergency_brake()

                        except RuntimeError:
                            pass

                        status_message = (
                            "EMERGENCY BRAKE"
                        )

                    # -----------------------------------------
                    # LOCK
                    # -----------------------------------------

                    elif event.key == pygame.K_1:

                        try:

                            bcm.lock_doors()

                            status_message = (
                                "Doors LOCKED"
                            )

                        except RuntimeError as error:

                            status_message = str(error)

                    # -----------------------------------------
                    # UNLOCK
                    # -----------------------------------------

                    elif event.key == pygame.K_2:

                        try:

                            bcm.unlock_doors()

                            status_message = (
                                "Doors UNLOCKED"
                            )

                        except RuntimeError as error:

                            status_message = str(error)

                    # -----------------------------------------
                    # OPEN
                    # -----------------------------------------

                    elif event.key == pygame.K_3:

                        if (
                            vehicle_state.speed_kmh
                            > 1.0
                        ):

                            status_message = (
                                "Cannot open doors "
                                "while moving"
                            )

                        else:

                            try:

                                bcm.open_doors()

                                status_message = (
                                    "Doors OPEN"
                                )

                            except RuntimeError as error:

                                status_message = str(error)

                    # -----------------------------------------
                    # CLOSE
                    # -----------------------------------------

                    elif event.key == pygame.K_4:

                        try:

                            bcm.close_doors()

                            status_message = (
                                "Doors CLOSED"
                            )

                        except RuntimeError as error:

                            status_message = str(error)

                    # -----------------------------------------
                    # CAMERA
                    # -----------------------------------------

                    elif event.key == pygame.K_c:

                        camera_index = (
                            camera_index + 1
                        ) % len(CAMERA_VIEWS)

                        current_camera = (
                            CAMERA_VIEWS[
                                camera_index
                            ]
                        )

                        try:

                            bridge.set_camera_view(
                                current_camera
                            )

                            status_message = (
                                "Camera: "
                                + current_camera.upper()
                            )

                        except RuntimeError as error:

                            status_message = str(error)

                    # -----------------------------------------
                    # RESET
                    # -----------------------------------------

                    elif event.key == pygame.K_r:

                        throttle = 0.0
                        brake = 0.0
                        steer = 0.0

                        try:

                            bridge.reset_vehicle()

                            status_message = (
                                "Vehicle RESET"
                            )

                        except RuntimeError as error:

                            status_message = str(error)

            # -------------------------------------------------
            # KEYBOARD STATE
            # -------------------------------------------------

            keys = pygame.key.get_pressed()

            # -------------------------------------------------
            # SAFETY
            # -------------------------------------------------

            controls_inhibited = (
                vehicle_state.doors_open
                or vehicle_state.vehicle_disabled_flag
            )

            # -------------------------------------------------
            # THROTTLE
            # -------------------------------------------------

            throttle_target = 0.0

            if (
                keys[pygame.K_w]
                or keys[pygame.K_UP]
            ):

                throttle_target = (
                    MAX_THROTTLE
                )

            if controls_inhibited:

                throttle_target = 0.0

            throttle = approach(
                throttle,
                throttle_target,
                THROTTLE_RESPONSE * dt
            )

            # -------------------------------------------------
            # BRAKE
            # -------------------------------------------------

            brake_target = 0.0

            if (
                keys[pygame.K_s]
                or keys[pygame.K_DOWN]
                or keys[pygame.K_SPACE]
            ):

                brake_target = 1.0

            if controls_inhibited:

                brake_target = 1.0

            brake = approach(
                brake,
                brake_target,
                BRAKE_RESPONSE * dt
            )

            # -------------------------------------------------
            # STEERING
            # -------------------------------------------------

            steer_target = 0.0

            if (
                keys[pygame.K_a]
                or keys[pygame.K_LEFT]
            ):

                steer_target = -1.0

            elif (
                keys[pygame.K_d]
                or keys[pygame.K_RIGHT]
            ):

                steer_target = 1.0

            steer = approach(
                steer,
                steer_target,
                (
                    STEER_RESPONSE
                    if steer_target != 0.0
                    else STEER_RETURN
                ) * dt
            )

            # -------------------------------------------------
            # VCU → CARLA
            # -------------------------------------------------

            try:

                vcu.apply_command(
                    throttle=throttle,
                    brake=brake,
                    steer=steer
                )

            except RuntimeError as error:

                status_message = str(error)

                throttle = 0.0
                brake = 1.0

            # -------------------------------------------------
            # DIGITAL TWIN
            # -------------------------------------------------

            try:

                manager.tick()

            except Exception as error:

                status_message = (
                    "Digital Twin Error: "
                    + str(error)
                )

            # -------------------------------------------------
            # FOLLOW CAR
            # -------------------------------------------------

            try:

                bridge.follow_vehicle()

            except Exception:
                pass

            # -------------------------------------------------
            # CAMERA FRAME
            # -------------------------------------------------

            frame = create_camera_surface(
                bridge.get_camera_frame(),
                CAMERA_WIDTH,
                CAMERA_HEIGHT
            )

            # =================================================
            # DRAW SCREEN
            # =================================================

            screen.fill(
                (10, 15, 22)
            )

            # -------------------------------------------------
            # HEADER
            # -------------------------------------------------

            pygame.draw.rect(
                screen,
                (18, 28, 40),
                (
                    0,
                    0,
                    WINDOW_WIDTH,
                    60
                )
            )

            draw_text(
                screen,
                title_font,
                "SECUREEV",
                18,
                16,
                (70, 220, 170)
            )

            draw_text(
                screen,
                font,
                "MANUAL DRIVING",
                160,
                21
            )

            draw_text(
                screen,
                small_font,
                (
                    "CARLA | "
                    + current_camera.upper()
                ),
                745,
                22,
                (70, 220, 170)
            )

            # -------------------------------------------------
            # CAMERA
            # -------------------------------------------------

            pygame.draw.rect(
                screen,
                (15, 22, 30),
                (
                    15,
                    75,
                    CAMERA_WIDTH,
                    CAMERA_HEIGHT
                )
            )

            if frame is not None:

                screen.blit(
                    frame,
                    (
                        15,
                        75
                    )
                )

            else:

                draw_text(
                    screen,
                    font,
                    "Waiting for camera...",
                    230,
                    245
                )

            # -------------------------------------------------
            # RIGHT CONTROL PANEL
            # -------------------------------------------------

            draw_panel(
                screen,
                (
                    670,
                    75,
                    215,
                    220
                ),
                "CONTROLS",
                heading_font
            )

            control_lines = [

                "W / ↑  Accelerate",

                "S / ↓  Brake",

                "A / ←  Left",

                "D / →  Right",

                "SPACE  Emergency",

                "R      Reset",

                "ESC    Exit"
            ]

            y = 112

            for line in control_lines:

                draw_text(
                    screen,
                    small_font,
                    line,
                    685,
                    y
                )

                y += 27

            # -------------------------------------------------
            # VEHICLE FUNCTIONS
            # -------------------------------------------------

            draw_panel(
                screen,
                (
                    670,
                    310,
                    215,
                    150
                ),
                "VEHICLE FUNCTIONS",
                heading_font
            )

            function_lines = [

                "1  Lock",

                "2  Unlock",

                "3  Open",

                "4  Close",

                "C  Camera"
            ]

            y = 345

            for line in function_lines:

                draw_text(
                    screen,
                    small_font,
                    line,
                    685,
                    y
                )

                y += 22

            # -------------------------------------------------
            # TELEMETRY
            # -------------------------------------------------

            draw_panel(
                screen,
                (
                    15,
                    450,
                    430,
                    135
                ),
                "LIVE TELEMETRY",
                heading_font
            )

            gps = (
                vehicle_state.reported_gps
            )

            if gps:

                gps_text = (
                    f"{gps['x']:.1f}, "
                    f"{gps['y']:.1f}"
                )

            else:

                gps_text = "N/A"

            telemetry_left = [

                (
                    "Speed",
                    f"{vehicle_state.speed_kmh:.1f} km/h"
                ),

                (
                    "Battery",
                    f"{vehicle_state.battery_soc:.1f}%"
                ),

                (
                    "Batt Temp",
                    f"{vehicle_state.battery_temp:.1f} C"
                ),

                (
                    "Motor RPM",
                    f"{vehicle_state.motor_rpm:.0f}"
                )
            ]

            telemetry_right = [

                (
                    "Motor Temp",
                    f"{vehicle_state.motor_temp:.1f} C"
                ),

                (
                    "Accel",
                    f"{vehicle_state.acceleration:.2f} m/s2"
                ),

                (
                    "Doors",
                    (
                        "OPEN"
                        if vehicle_state.doors_open
                        else "CLOSED"
                    )
                ),

                (
                    "GPS",
                    gps_text
                )
            ]

            for i, (
                label,
                value
            ) in enumerate(
                telemetry_left
            ):

                y = (
                    485
                    + i * 24
                )

                draw_text(
                    screen,
                    small_font,
                    f"{label}:",
                    30,
                    y
                )

                draw_text(
                    screen,
                    small_font,
                    value,
                    125,
                    y,
                    (70, 220, 170)
                )

            for i, (
                label,
                value
            ) in enumerate(
                telemetry_right
            ):

                y = (
                    485
                    + i * 24
                )

                draw_text(
                    screen,
                    small_font,
                    f"{label}:",
                    225,
                    y
                )

                draw_text(
                    screen,
                    small_font,
                    value,
                    320,
                    y,
                    (70, 220, 170)
                )

            # -------------------------------------------------
            # ECU STATUS
            # -------------------------------------------------

            draw_panel(
                screen,
                (
                    460,
                    450,
                    425,
                    135
                ),
                "ECU STATUS",
                heading_font
            )

            ecu_list = [

                ("VCU", vcu.status),

                ("BMS", bms.status),

                ("BCM", bcm.status),

                ("MCU", mcu.status),

                ("TCU", tcu.status)
            ]

            x_positions = [
                475,
                555,
                635,
                715,
                795
            ]

            for i, (
                ecu_name,
                status
            ) in enumerate(
                ecu_list
            ):

                x = x_positions[i]

                draw_text(
                    screen,
                    small_font,
                    ecu_name,
                    x,
                    490
                )

                status_color = (
                    (70, 220, 170)
                    if status == "ONLINE"
                    else (240, 80, 80)
                )

                draw_text(
                    screen,
                    small_font,
                    status,
                    x,
                    515,
                    status_color
                )

            draw_text(
                screen,
                small_font,
                f"Throttle: {throttle:.2f}",
                475,
                550
            )

            draw_text(
                screen,
                small_font,
                f"Brake: {brake:.2f}",
                600,
                550
            )

            draw_text(
                screen,
                small_font,
                f"Steer: {steer:+.2f}",
                715,
                550
            )

            # -------------------------------------------------
            # STATUS BAR
            # -------------------------------------------------

            pygame.draw.rect(
                screen,
                (15, 42, 39),
                (
                    15,
                    590,
                    870,
                    20
                )
            )

            draw_text(
                screen,
                small_font,
                status_message,
                25,
                592,
                (70, 220, 170)
            )

            pygame.display.flip()

        # =====================================================
        # SAFE STOP
        # =====================================================

        print(
            "\nStopping vehicle safely...",
            flush=True
        )

        try:

            vcu.apply_command(
                throttle=0.0,
                brake=1.0,
                steer=0.0
            )

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

        print(
            "Manual driving session ended.",
            flush=True
        )


if __name__ == "__main__":

    main()