"""SecureEV CARLA integration layer.

This is the only module that communicates directly with CARLA.
"""

from __future__ import annotations

from io import BytesIO
import math
import random
import threading
import time

import carla
from PIL import Image


class CarlaBridge:
    """Connection, vehicle, camera, ground-truth and spectator adapter."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 2000,
        timeout: float = 10.0,
    ) -> None:
        print(f"[CarlaBridge] Connecting to {host}:{port}...", flush=True)
        self.client = carla.Client(host, port)
        self.client.set_timeout(timeout)
        self.world = self.client.get_world()

        self.vehicle = None

        # CARLA Traffic Manager controls autonomous patrol mode.
        # Use a dedicated port so it does not collide with FastAPI on 8000.
        self.traffic_manager = None
        self.traffic_manager_port = 8001
        self.autopilot_enabled = False
        self.patrol_seed: int | None = None
        self.patrol_speed_kmh = 28.0

        self.camera = None
        self.camera_frame: bytes | None = None
        self.camera_jpeg: bytes | None = None
        self.camera_width = 320
        self.camera_height = 180
        self.camera_view = "front"
        self._camera_lock = threading.Lock()

        self._spectator_initialized = False
        self._spectator_last_time: float | None = None

        self._previous_speed_mps = 0.0
        self._previous_state_time: float | None = None

    # =========================================================
    # VEHICLE
    # =========================================================

    def spawn_vehicle(
        self,
        blueprint_id: str = "vehicle.tesla.model3",
        spawn_index: int = 0,
    ):
        if self.vehicle is not None:
            raise RuntimeError("A vehicle is already spawned.")

        blueprint_library = self.world.get_blueprint_library()
        vehicle_bp = blueprint_library.find(blueprint_id)
        spawn_points = self.world.get_map().get_spawn_points()
        if not spawn_points:
            raise RuntimeError("CARLA returned no spawn points.")

        spawn_index = max(0, min(int(spawn_index), len(spawn_points) - 1))
        spawn_point = spawn_points[spawn_index]
        self.vehicle = self.world.spawn_actor(vehicle_bp, spawn_point)
        self._previous_speed_mps = 0.0
        self._previous_state_time = time.monotonic()
        self._spectator_initialized = False
        self._spectator_last_time = None

        print(
            f"[CarlaBridge] Spawned {self.vehicle.type_id} at {spawn_point.location}",
            flush=True,
        )
        return self.vehicle

    def set_autopilot(
        self,
        enabled: bool = True,
        *,
        target_speed_kmh: float = 28.0,
        random_seed: int | None = None,
    ) -> None:
        """Enable CARLA Traffic Manager autopilot for safe urban patrols."""
        if self.vehicle is None:
            raise RuntimeError("No vehicle spawned yet. Call spawn_vehicle() first.")

        if not enabled:
            if self.traffic_manager is not None:
                self.vehicle.set_autopilot(False, self.traffic_manager.get_port())
            else:
                self.vehicle.set_autopilot(False)
            self.autopilot_enabled = False
            return

        target_speed_kmh = max(5.0, min(60.0, float(target_speed_kmh)))
        if random_seed is None:
            random_seed = random.SystemRandom().randint(1, 2_147_483_647)

        self.traffic_manager = self.client.get_trafficmanager(self.traffic_manager_port)
        tm = self.traffic_manager
        self.patrol_seed = int(random_seed)
        self.patrol_speed_kmh = target_speed_kmh

        # These settings keep the EV on CARLA's road network, respect signals,
        # maintain distance from traffic, and allow realistic route variation.
        if hasattr(tm, "set_random_device_seed"):
            tm.set_random_device_seed(self.patrol_seed)
        if hasattr(tm, "set_desired_speed"):
            tm.set_desired_speed(self.vehicle, target_speed_kmh)
        if hasattr(tm, "distance_to_leading_vehicle"):
            tm.distance_to_leading_vehicle(self.vehicle, 7.0)
        if hasattr(tm, "auto_lane_change"):
            tm.auto_lane_change(self.vehicle, True)
        if hasattr(tm, "random_left_lanechange_percentage"):
            tm.random_left_lanechange_percentage(self.vehicle, 8.0)
        if hasattr(tm, "random_right_lanechange_percentage"):
            tm.random_right_lanechange_percentage(self.vehicle, 8.0)
        if hasattr(tm, "ignore_lights_percentage"):
            tm.ignore_lights_percentage(self.vehicle, 0.0)
        if hasattr(tm, "ignore_signs_percentage"):
            tm.ignore_signs_percentage(self.vehicle, 0.0)
        if hasattr(tm, "keep_right_rule_percentage"):
            tm.keep_right_rule_percentage(self.vehicle, 70.0)
        if hasattr(tm, "update_vehicle_lights"):
            tm.update_vehicle_lights(self.vehicle, True)

        self.vehicle.set_autopilot(True, tm.get_port())
        self.autopilot_enabled = True

    def start_autonomous_patrol(
        self,
        target_speed_kmh: float = 28.0,
        random_seed: int | None = None,
    ) -> dict:
        """Start/restart an autonomous urban patrol with a fresh route seed.

        Traffic Manager generates an endless road-network trajectory and can
        choose different branches at junctions. A new seed gives different
        route choices between patrol sessions.
        """
        self.set_autopilot(
            True,
            target_speed_kmh=target_speed_kmh,
            random_seed=random_seed,
        )
        return self.get_autonomy_status()

    def set_patrol_target_speed(self, target_speed_kmh: float) -> None:
        """Adjust the active Traffic Manager target without taking ownership."""
        if self.vehicle is None:
            raise RuntimeError("No vehicle spawned yet.")
        if not self.autopilot_enabled or self.traffic_manager is None:
            raise RuntimeError("Traffic Manager patrol is not active.")
        target_speed_kmh = max(5.0, min(60.0, float(target_speed_kmh)))
        self.traffic_manager.set_desired_speed(self.vehicle, target_speed_kmh)
        self.patrol_speed_kmh = target_speed_kmh

    def stop_autonomous_patrol(self) -> None:
        self.set_autopilot(False)

    def emergency_stop(self) -> None:
        """Leave autopilot and request a controlled full brake.

        CARLA's physics engine must decelerate the vehicle.  Overwriting
        velocity here creates discontinuities that can launch or destabilize
        the vehicle, especially when called while Traffic Manager is active.
        """
        if self.vehicle is None:
            return
        self.set_autopilot(False)
        self.vehicle.apply_control(
            carla.VehicleControl(throttle=0.0, brake=1.0, steer=0.0)
        )

    def get_autonomy_status(self) -> dict:
        next_action = None
        if self.autopilot_enabled and self.traffic_manager is not None and self.vehicle is not None:
            try:
                action = self.traffic_manager.get_next_action(self.vehicle)
                if action and len(action) >= 1:
                    next_action = str(action[0])
            except Exception:
                next_action = None
        return {
            "enabled": self.autopilot_enabled,
            "mode": "AUTONOMOUS_PATROL" if self.autopilot_enabled else "MANUAL",
            "target_speed_kmh": self.patrol_speed_kmh,
            "traffic_manager_port": self.traffic_manager.get_port() if self.traffic_manager is not None else None,
            "patrol_seed": self.patrol_seed,
            "next_maneuver": next_action,
        }

    def apply_control(
        self,
        throttle: float = 0.0,
        brake: float = 0.0,
        steer: float = 0.0,
    ) -> None:
        if self.vehicle is None:
            raise RuntimeError("No vehicle spawned yet. Call spawn_vehicle() first.")
        throttle = max(0.0, min(1.0, float(throttle)))
        brake = max(0.0, min(1.0, float(brake)))
        steer = max(-1.0, min(1.0, float(steer)))
        self.vehicle.apply_control(
            carla.VehicleControl(
                throttle=throttle,
                brake=brake,
                steer=steer,
            )
        )

    # =========================================================
    # GROUND TRUTH
    # =========================================================

    def get_ground_truth_state(self) -> dict:
        if self.vehicle is None:
            raise RuntimeError("No vehicle spawned yet. Call spawn_vehicle() first.")

        now = time.time()
        velocity = self.vehicle.get_velocity()
        speed_mps = math.sqrt(velocity.x**2 + velocity.y**2 + velocity.z**2)
        speed_kmh = speed_mps * 3.6

        acceleration_mps2 = 0.0
        current_mono = time.monotonic()
        if self._previous_state_time is not None:
            dt = current_mono - self._previous_state_time
            if dt > 0:
                acceleration_mps2 = (speed_mps - self._previous_speed_mps) / dt
        self._previous_speed_mps = speed_mps
        self._previous_state_time = current_mono

        transform = self.vehicle.get_transform()
        rotation = transform.rotation
        return {
            "speed_kmh": round(speed_kmh, 2),
            "acceleration_mps2": round(acceleration_mps2, 3),
            "location": {
                "x": round(transform.location.x, 2),
                "y": round(transform.location.y, 2),
                "z": round(transform.location.z, 2),
            },
            "rotation": {
                "pitch": round(rotation.pitch, 2),
                "yaw": round(rotation.yaw, 2),
                "roll": round(rotation.roll, 2),
            },
            "timestamp": now,
        }

    # =========================================================
    # SMOOTH THIRD-PERSON SPECTATOR
    # =========================================================

    def follow_vehicle(
        self,
        distance: float = 10.0,
        height: float = 4.5,
        pitch: float = -16.0,
        smoothing: float = 10.0,
    ) -> None:
        """Smoothly follow the vehicle with frame-rate-independent damping."""
        if self.vehicle is None:
            return

        distance = max(3.0, float(distance))
        height = max(1.5, float(height))
        smoothing = max(1.0, min(30.0, float(smoothing)))

        transform = self.vehicle.get_transform()
        forward = transform.get_forward_vector()
        target_location = carla.Location(
            x=transform.location.x - forward.x * distance,
            y=transform.location.y - forward.y * distance,
            z=transform.location.z + height,
        )
        target_rotation = carla.Rotation(
            pitch=float(pitch),
            yaw=transform.rotation.yaw,
            roll=0.0,
        )
        target = carla.Transform(target_location, target_rotation)
        spectator = self.world.get_spectator()
        now = time.monotonic()

        if not self._spectator_initialized:
            spectator.set_transform(target)
            self._spectator_initialized = True
            self._spectator_last_time = now
            return

        previous_time = self._spectator_last_time
        self._spectator_last_time = now
        dt = 0.05 if previous_time is None else max(0.001, min(0.2, now - previous_time))
        alpha = 1.0 - math.exp(-smoothing * dt)
        current = spectator.get_transform()

        def lerp(a: float, b: float) -> float:
            return a + (b - a) * alpha

        yaw_delta = ((target.rotation.yaw - current.rotation.yaw + 180.0) % 360.0) - 180.0
        spectator.set_transform(
            carla.Transform(
                carla.Location(
                    x=lerp(current.location.x, target.location.x),
                    y=lerp(current.location.y, target.location.y),
                    z=lerp(current.location.z, target.location.z),
                ),
                carla.Rotation(
                    pitch=lerp(current.rotation.pitch, target.rotation.pitch),
                    yaw=current.rotation.yaw + yaw_delta * alpha,
                    roll=0.0,
                ),
            )
        )

    # =========================================================
    # RGB CAMERA
    # =========================================================

    def attach_rgb_camera(
        self,
        width: int = 640,
        height: int = 360,
        fov: float = 90.0,
    ):
        if self.vehicle is None:
            raise RuntimeError("No vehicle spawned yet.")

        self._destroy_camera()
        self.camera_width = int(width)
        self.camera_height = int(height)

        camera_bp = self.world.get_blueprint_library().find("sensor.camera.rgb")
        camera_bp.set_attribute("image_size_x", str(width))
        camera_bp.set_attribute("image_size_y", str(height))
        camera_bp.set_attribute("fov", str(fov))
        camera_bp.set_attribute("sensor_tick", "0.20")

        self.camera = self.world.spawn_actor(
            camera_bp,
            self._get_camera_transform("front"),
            attach_to=self.vehicle,
        )
        self.camera.listen(self._camera_callback)
        self.camera_view = "front"
        print("[CarlaBridge] RGB camera attached.", flush=True)
        return self.camera

    def _get_camera_transform(self, view: str):
        view = view.lower().strip()
        transforms = {
            "front": carla.Transform(carla.Location(x=1.5, y=0.0, z=1.8), carla.Rotation(pitch=-5.0, yaw=0.0)),
            "rear": carla.Transform(carla.Location(x=-1.5, y=0.0, z=1.8), carla.Rotation(pitch=-5.0, yaw=180.0)),
            "left": carla.Transform(carla.Location(x=0.0, y=-1.2, z=1.6), carla.Rotation(pitch=-5.0, yaw=-90.0)),
            "right": carla.Transform(carla.Location(x=0.0, y=1.2, z=1.6), carla.Rotation(pitch=-5.0, yaw=90.0)),
        }
        try:
            return transforms[view]
        except KeyError as exc:
            raise ValueError("Invalid camera view. Use front, rear, left or right.") from exc

    def disable_rgb_camera(self) -> None:
        """Stop and destroy the RGB camera sensor without affecting the vehicle."""
        self._destroy_camera()

    def set_camera_view(self, view: str) -> None:
        if self.camera is None:
            raise RuntimeError("RGB camera is not attached.")
        self.camera.set_transform(self._get_camera_transform(view))
        self.camera_view = view.lower().strip()

    def _camera_callback(self, image) -> None:
        raw = bytes(image.raw_data)
        try:
            pil_image = Image.frombytes(
                "RGBA",
                (image.width, image.height),
                raw,
                "raw",
                "BGRA",
            ).convert("RGB")
            output = BytesIO()
            pil_image.save(output, format="JPEG", quality=55)
            jpeg = output.getvalue()
        except Exception:
            jpeg = None

        with self._camera_lock:
            self.camera_frame = raw
            if jpeg:
                self.camera_jpeg = jpeg

    def get_camera_frame(self) -> bytes | None:
        with self._camera_lock:
            return self.camera_frame

    def get_camera_jpeg(self) -> bytes | None:
        with self._camera_lock:
            return self.camera_jpeg

    # =========================================================
    # RESET / CLEANUP
    # =========================================================

    def reset_vehicle(self, spawn_index: int = 0) -> None:
        if self.vehicle is None:
            raise RuntimeError("No vehicle spawned yet.")
        spawn_points = self.world.get_map().get_spawn_points()
        if not spawn_points:
            raise RuntimeError("No CARLA spawn points available.")
        spawn_index = max(0, min(int(spawn_index), len(spawn_points) - 1))

        self.set_autopilot(False)
        self.vehicle.apply_control(carla.VehicleControl(throttle=0.0, brake=1.0, steer=0.0))
        self.vehicle.set_transform(spawn_points[spawn_index])
        self.vehicle.set_target_velocity(carla.Vector3D())
        self.vehicle.set_target_angular_velocity(carla.Vector3D())

        self._previous_speed_mps = 0.0
        self._previous_state_time = time.monotonic()
        self._spectator_initialized = False
        self._spectator_last_time = None

    def _destroy_camera(self) -> None:
        if self.camera is None:
            return
        try:
            self.camera.stop()
        except Exception:
            pass
        try:
            self.camera.destroy()
        except Exception:
            pass
        self.camera = None
        with self._camera_lock:
            self.camera_frame = None
            self.camera_jpeg = None

    def cleanup(self) -> None:
        self._destroy_camera()
        if self.vehicle is not None:
            try:
                self.set_autopilot(False)
                self.vehicle.apply_control(carla.VehicleControl(throttle=0.0, brake=1.0, steer=0.0))
            except Exception:
                pass
            try:
                self.vehicle.destroy()
            except Exception:
                pass
            self.vehicle = None
            print("[CarlaBridge] Vehicle destroyed, cleaned up.", flush=True)

    def __str__(self) -> str:
        return "CarlaBridge [No Vehicle]" if self.vehicle is None else f"CarlaBridge [{self.vehicle.type_id}]"
