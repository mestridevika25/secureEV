"""
carla_bridge.py

SecureEV - CARLA Integration Layer

IMPORTANT ARCHITECTURE RULE
---------------------------
This is the ONLY module in SecureEV that communicates
directly with CARLA.

All other modules interact with CARLA through CarlaBridge.

Responsibilities:
    - Connect to CARLA
    - Spawn vehicle
    - Read ground-truth state
    - Apply vehicle control
    - Attach / control camera sensors
    - Move third-person spectator
    - Reset vehicle
    - Cleanup CARLA actors
"""

from __future__ import annotations

import math
import time

import carla


class CarlaBridge:

    def __init__(
        self,
        host: str = "localhost",
        port: int = 2000,
        timeout: float = 10.0,
    ):

        print(
            f"[CarlaBridge] Connecting to "
            f"{host}:{port}...",
            flush=True
        )

        self.client = carla.Client(
            host,
            port
        )

        self.client.set_timeout(
            timeout
        )

        self.world = self.client.get_world()

        self.vehicle = None

        # -----------------------------------------------------
        # Camera
        # -----------------------------------------------------

        self.camera = None
        self.camera_frame = None

        self.camera_width = 800
        self.camera_height = 450
        self.camera_view = "front"

        # -----------------------------------------------------
        # Ground-truth acceleration tracking
        # -----------------------------------------------------

        self._previous_speed_mps = 0.0
        self._previous_state_time = None

    # =========================================================
    # VEHICLE SPAWN
    # =========================================================

    def spawn_vehicle(
        self,
        blueprint_id: str = "vehicle.tesla.model3",
        spawn_index: int = 0,
    ):

        if self.vehicle is not None:

            raise RuntimeError(
                "A vehicle is already spawned."
            )

        blueprint_library = (
            self.world.get_blueprint_library()
        )

        vehicle_bp = blueprint_library.find(
            blueprint_id
        )

        spawn_points = (
            self.world
            .get_map()
            .get_spawn_points()
        )

        if not spawn_points:

            raise RuntimeError(
                "CARLA returned no spawn points."
            )

        if spawn_index < 0:

            spawn_index = 0

        if spawn_index >= len(spawn_points):

            spawn_index = 0

        spawn_point = spawn_points[
            spawn_index
        ]

        self.vehicle = (
            self.world.spawn_actor(
                vehicle_bp,
                spawn_point
            )
        )

        self._previous_speed_mps = 0.0
        self._previous_state_time = time.time()

        print(
            "[CarlaBridge] Spawned "
            f"{self.vehicle.type_id} "
            f"at {spawn_point.location}",
            flush=True
        )

        return self.vehicle

    # =========================================================
    # GROUND TRUTH
    # =========================================================

    def get_ground_truth_state(self) -> dict:

        if self.vehicle is None:

            raise RuntimeError(
                "No vehicle spawned yet. "
                "Call spawn_vehicle() first."
            )

        now = time.time()

        velocity = (
            self.vehicle.get_velocity()
        )

        speed_mps = math.sqrt(
            velocity.x ** 2
            + velocity.y ** 2
            + velocity.z ** 2
        )

        speed_kmh = (
            speed_mps * 3.6
        )

        # -----------------------------------------------------
        # Acceleration
        # -----------------------------------------------------

        acceleration_mps2 = 0.0

        if self._previous_state_time is not None:

            dt = (
                now
                - self._previous_state_time
            )

            if dt > 0:

                acceleration_mps2 = (
                    speed_mps
                    - self._previous_speed_mps
                ) / dt

        self._previous_speed_mps = speed_mps
        self._previous_state_time = now

        # -----------------------------------------------------
        # Transform
        # -----------------------------------------------------

        transform = (
            self.vehicle.get_transform()
        )

        rotation = transform.rotation

        # -----------------------------------------------------
        # Return state
        # -----------------------------------------------------

        return {

            "speed_kmh": round(
                speed_kmh,
                2
            ),

            "acceleration_mps2": round(
                acceleration_mps2,
                3
            ),

            "location": {
                "x": round(
                    transform.location.x,
                    2
                ),
                "y": round(
                    transform.location.y,
                    2
                ),
                "z": round(
                    transform.location.z,
                    2
                ),
            },

            "rotation": {
                "pitch": round(
                    rotation.pitch,
                    2
                ),
                "yaw": round(
                    rotation.yaw,
                    2
                ),
                "roll": round(
                    rotation.roll,
                    2
                ),
            },

            "timestamp": now,
        }

    # =========================================================
    # AUTOPILOT
    # =========================================================

    def set_autopilot(
        self,
        enabled: bool = True
    ):

        if self.vehicle is None:

            raise RuntimeError(
                "No vehicle spawned yet. "
                "Call spawn_vehicle() first."
            )

        self.vehicle.set_autopilot(
            enabled
        )

    # =========================================================
    # VEHICLE CONTROL
    # =========================================================

    def apply_control(
        self,
        throttle: float = 0.0,
        brake: float = 0.0,
        steer: float = 0.0,
    ):

        if self.vehicle is None:

            raise RuntimeError(
                "No vehicle spawned yet. "
                "Call spawn_vehicle() first."
            )

        throttle = max(
            0.0,
            min(
                1.0,
                float(throttle)
            )
        )

        brake = max(
            0.0,
            min(
                1.0,
                float(brake)
            )
        )

        steer = max(
            -1.0,
            min(
                1.0,
                float(steer)
            )
        )

        control = (
            carla.VehicleControl(
                throttle=throttle,
                brake=brake,
                steer=steer
            )
        )

        self.vehicle.apply_control(
            control
        )

    # =========================================================
    # THIRD-PERSON SPECTATOR
    # =========================================================

    def follow_vehicle(
        self,
        distance: float = 8.0,
        height: float = 3.5,
        pitch: float = -12.0,
    ):

        if self.vehicle is None:

            raise RuntimeError(
                "No vehicle spawned yet."
            )

        transform = (
            self.vehicle.get_transform()
        )

        forward = (
            transform
            .get_forward_vector()
        )

        camera_location = (
            carla.Location(
                x=(
                    transform.location.x
                    - forward.x * distance
                ),
                y=(
                    transform.location.y
                    - forward.y * distance
                ),
                z=(
                    transform.location.z
                    + height
                ),
            )
        )

        camera_rotation = (
            carla.Rotation(
                pitch=pitch,
                yaw=transform.rotation.yaw,
                roll=0.0,
            )
        )

        spectator = (
            self.world.get_spectator()
        )

        spectator.set_transform(
            carla.Transform(
                camera_location,
                camera_rotation
            )
        )

    # =========================================================
    # RGB CAMERA
    # =========================================================

    def attach_rgb_camera(
        self,
        width: int = 800,
        height: int = 450,
        fov: float = 90.0,
    ):

        if self.vehicle is None:

            raise RuntimeError(
                "No vehicle spawned yet."
            )

        # -----------------------------------------------------
        # Remove existing camera
        # -----------------------------------------------------

        if self.camera is not None:

            try:
                self.camera.stop()
            except Exception:
                pass

            self.camera.destroy()

            self.camera = None
            self.camera_frame = None

        self.camera_width = width
        self.camera_height = height

        blueprint_library = (
            self.world.get_blueprint_library()
        )

        camera_bp = (
            blueprint_library.find(
                "sensor.camera.rgb"
            )
        )

        camera_bp.set_attribute(
            "image_size_x",
            str(width)
        )

        camera_bp.set_attribute(
            "image_size_y",
            str(height)
        )

        camera_bp.set_attribute(
            "fov",
            str(fov)
        )

        # Reduced camera rate to keep CPU/GPU usage
        # reasonable for the laptop.
        camera_bp.set_attribute(
            "sensor_tick",
            "0.10"
        )

        camera_transform = (
            self._get_camera_transform(
                "front"
            )
        )

        self.camera = (
            self.world.spawn_actor(
                camera_bp,
                camera_transform,
                attach_to=self.vehicle
            )
        )

        self.camera.listen(
            self._camera_callback
        )

        self.camera_view = "front"

        print(
            "[CarlaBridge] RGB camera attached.",
            flush=True
        )

        return self.camera

    # =========================================================
    # CAMERA VIEW TRANSFORM
    # =========================================================

    def _get_camera_transform(
        self,
        view: str
    ):

        view = view.lower().strip()

        if view == "front":

            return carla.Transform(
                carla.Location(
                    x=1.5,
                    y=0.0,
                    z=1.8
                ),
                carla.Rotation(
                    pitch=-5.0,
                    yaw=0.0,
                    roll=0.0
                )
            )

        if view == "rear":

            return carla.Transform(
                carla.Location(
                    x=-1.5,
                    y=0.0,
                    z=1.8
                ),
                carla.Rotation(
                    pitch=-5.0,
                    yaw=180.0,
                    roll=0.0
                )
            )

        if view == "left":

            return carla.Transform(
                carla.Location(
                    x=0.0,
                    y=-1.2,
                    z=1.6
                ),
                carla.Rotation(
                    pitch=-5.0,
                    yaw=-90.0,
                    roll=0.0
                )
            )

        if view == "right":

            return carla.Transform(
                carla.Location(
                    x=0.0,
                    y=1.2,
                    z=1.6
                ),
                carla.Rotation(
                    pitch=-5.0,
                    yaw=90.0,
                    roll=0.0
                )
            )

        raise ValueError(
            "Invalid camera view. "
            "Use front, rear, left or right."
        )

    # =========================================================
    # SET CAMERA VIEW
    # =========================================================

    def set_camera_view(
        self,
        view: str
    ):

        if self.camera is None:

            raise RuntimeError(
                "RGB camera is not attached."
            )

        view = view.lower().strip()

        transform = (
            self._get_camera_transform(
                view
            )
        )

        self.camera.set_transform(
            transform
        )

        self.camera_view = view

    # =========================================================
    # CAMERA CALLBACK
    # =========================================================

    def _camera_callback(
        self,
        image
    ):

        self.camera_frame = bytes(
            image.raw_data
        )

    # =========================================================
    # GET CAMERA FRAME
    # =========================================================

    def get_camera_frame(self):

        return self.camera_frame

    # =========================================================
    # RESET VEHICLE
    # =========================================================

    def reset_vehicle(
        self,
        spawn_index: int = 0
    ):

        if self.vehicle is None:

            raise RuntimeError(
                "No vehicle spawned yet."
            )

        spawn_points = (
            self.world
            .get_map()
            .get_spawn_points()
        )

        if not spawn_points:

            raise RuntimeError(
                "No CARLA spawn points available."
            )

        if (
            spawn_index < 0
            or spawn_index >= len(spawn_points)
        ):

            spawn_index = 0

        # Disable autopilot.
        self.vehicle.set_autopilot(
            False
        )

        # Stop movement.
        self.vehicle.apply_control(
            carla.VehicleControl(
                throttle=0.0,
                brake=1.0,
                steer=0.0
            )
        )

        # Move to spawn point.
        self.vehicle.set_transform(
            spawn_points[spawn_index]
        )

        # Clear velocity.
        self.vehicle.set_target_velocity(
            carla.Vector3D(
                x=0.0,
                y=0.0,
                z=0.0
            )
        )

        self.vehicle.set_target_angular_velocity(
            carla.Vector3D(
                x=0.0,
                y=0.0,
                z=0.0
            )
        )

        self._previous_speed_mps = 0.0
        self._previous_state_time = time.time()

        print(
            "[CarlaBridge] Vehicle reset.",
            flush=True
        )

    # =========================================================
    # CLEANUP
    # =========================================================

    def cleanup(self):

        # -----------------------------------------------------
        # Camera
        # -----------------------------------------------------

        if self.camera is not None:

            try:
                self.camera.stop()
            except Exception:
                pass

            try:
                self.camera.destroy()
            except Exception:
                pass

            self.camera = None
            self.camera_frame = None

        # -----------------------------------------------------
        # Vehicle
        # -----------------------------------------------------

        if self.vehicle is not None:

            try:

                self.vehicle.set_autopilot(
                    False
                )

                self.vehicle.apply_control(
                    carla.VehicleControl(
                        throttle=0.0,
                        brake=1.0,
                        steer=0.0
                    )
                )

            except Exception:
                pass

            try:
                self.vehicle.destroy()
            except Exception:
                pass

            print(
                "[CarlaBridge] Vehicle destroyed, cleaned up.",
                flush=True
            )

            self.vehicle = None

    # =========================================================
    # SIMPLE TEST
    # =========================================================

    def __str__(self):

        if self.vehicle is None:

            return "CarlaBridge [No Vehicle]"

        return (
            f"CarlaBridge "
            f"[{self.vehicle.type_id}]"
        )


if __name__ == "__main__":

    bridge = CarlaBridge()

    try:

        bridge.spawn_vehicle()

        bridge.set_autopilot(
            True
        )

        bridge.attach_rgb_camera()

        for _ in range(20):

            state = (
                bridge.get_ground_truth_state()
            )

            bridge.follow_vehicle()

            print(
                f"Speed: "
                f"{state['speed_kmh']:.2f} km/h | "
                f"Acceleration: "
                f"{state['acceleration_mps2']:.2f} m/s² | "
                f"Location: "
                f"{state['location']}",
                flush=True
            )

            time.sleep(0.5)

    finally:

        bridge.cleanup()