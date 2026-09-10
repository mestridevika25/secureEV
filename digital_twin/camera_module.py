"""
camera_module.py

Phase 3 — Camera sensor module.

The CARLA-facing work remains inside CarlaBridge. This module consumes frames
through the bridge, tracks whether the feed is live/replayed, and exposes
camera telemetry that can later be inspected by the Blue Team.
"""

from __future__ import annotations

import time
from typing import Optional

from digital_twin.base_ecu import BaseECU


class CameraModule(BaseECU):
    """Simulated vehicle camera ECU/sensor controller."""

    VALID_SOURCES = {"live", "replayed"}

    def __init__(self, vehicle_state, carla_bridge):
        super().__init__(
            ecu_id="CAM",
            vehicle_state=vehicle_state,
        )

        if carla_bridge is None:
            raise ValueError("carla_bridge cannot be None.")

        self.carla_bridge = carla_bridge
        self.last_frame_timestamp: Optional[float] = None
        self.last_frame_size = 0
        self.frame_available = False
        self.frame_sequence = 0
        self._replay_frame: Optional[bytes] = None

        self.vehicle_state.camera_feed_source = "live"

    def update(self) -> None:
        if not self.is_online():
            return

        if self.vehicle_state.camera_feed_source == "replayed":
            frame = self._replay_frame
        else:
            frame = self.carla_bridge.get_camera_frame()

        if frame is None:
            self.frame_available = False
            return

        self.frame_available = True
        self.last_frame_timestamp = time.time()
        self.last_frame_size = len(frame)
        self.frame_sequence += 1

    def get_frame(self) -> Optional[bytes]:
        """Return the currently selected live/replayed camera frame."""
        if not self.is_online():
            return None

        if self.vehicle_state.camera_feed_source == "replayed":
            return self._replay_frame

        return self.carla_bridge.get_camera_frame()

    def set_live_source(self) -> None:
        if not self.is_online():
            raise RuntimeError("Camera Module is offline.")

        self.vehicle_state.camera_feed_source = "live"
        self._replay_frame = None

    def set_replay_source(self, frame: bytes) -> None:
        if not self.is_online():
            raise RuntimeError("Camera Module is offline.")

        if not isinstance(frame, (bytes, bytearray)):
            raise TypeError("Replay frame must be bytes or bytearray.")

        if len(frame) == 0:
            raise ValueError("Replay frame cannot be empty.")

        self._replay_frame = bytes(frame)
        self.vehicle_state.camera_feed_source = "replayed"

    def clear_replay(self) -> None:
        self.set_live_source()

    def telemetry(self) -> dict:
        data = super().telemetry()
        data.update({
            "camera_feed_source": self.vehicle_state.camera_feed_source,
            "frame_available": self.frame_available,
            "last_frame_timestamp": self.last_frame_timestamp,
            "last_frame_size": self.last_frame_size,
            "frame_sequence": self.frame_sequence,
        })
        return data
