"""Manual driving command generation for the SecureEV digital twin."""

from __future__ import annotations

from typing import Mapping


class ManualController:
    """Translate named input actions into safe VCU commands."""

    ACTIONS = {
        "accelerate",
        "brake",
        "left",
        "right",
        "emergency_brake",
    }

    def __init__(self, vcu, throttle: float = 0.65):
        if vcu is None:
            raise ValueError("vcu cannot be None.")
        if not 0.0 <= throttle <= 1.0:
            raise ValueError("throttle must be between 0.0 and 1.0.")

        self.vcu = vcu
        self.throttle = throttle
        self.last_command = {
            "throttle": 0.0,
            "brake": 0.0,
            "steer": 0.0,
        }

    def update(self, keys: Mapping[str, bool]) -> dict:
        """Apply one control frame and return the command sent to the VCU.

        ``keys`` contains action names rather than framework-specific key codes,
        which keeps input handling separate from vehicle control and easy to test.
        """
        unknown_actions = set(keys) - self.ACTIONS
        if unknown_actions:
            raise ValueError(f"Unknown input actions: {sorted(unknown_actions)}")

        emergency = bool(keys.get("emergency_brake", False))
        accelerating = bool(keys.get("accelerate", False))
        braking = bool(keys.get("brake", False))

        if emergency:
            command = {"throttle": 0.0, "brake": 1.0, "steer": 0.0}
        else:
            command = {
                "throttle": self.throttle if accelerating and not braking else 0.0,
                "brake": 1.0 if braking else 0.0,
                "steer": self._steering(keys),
            }

        self.vcu.apply_command(**command)
        self.last_command = command
        return command.copy()

    def release(self) -> dict:
        """Release all controls and apply a neutral command."""
        return self.update({})

    @staticmethod
    def _steering(keys: Mapping[str, bool]) -> float:
        left = bool(keys.get("left", False))
        right = bool(keys.get("right", False))

        if left == right:
            return 0.0
        return -1.0 if left else 1.0