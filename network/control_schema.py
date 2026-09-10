"""
SecureEV control-message helpers for Phase 4F.

The control path is intentionally kept separate from the future security
layer. This module performs protocol/data validation only; later the Blue
Team security gateway will add identity, freshness, replay, policy and risk
checks before a command is allowed to reach an ECU.
"""

from __future__ import annotations

from typing import Any

from network.message_schema import create_message


VCU_COMMANDS = {
    "set_control",
    "emergency_brake",
}


def create_vcu_control_message(
    command: str,
    data: dict[str, Any] | None,
    sequence: int,
    vehicle_id: str = "SEV-001",
) -> dict[str, Any]:
    """Create a standard VCU control message."""

    command = str(command).strip().lower()
    if command not in VCU_COMMANDS:
        raise ValueError(f"Unsupported VCU command: {command}")

    if data is None:
        data = {}

    if not isinstance(data, dict):
        raise TypeError("data must be a dictionary.")

    if command == "set_control":
        required = {"throttle", "brake", "steer"}
        if not required.issubset(data.keys()):
            missing = sorted(required - set(data.keys()))
            raise ValueError(f"Missing VCU control fields: {missing}")

        throttle = float(data["throttle"])
        brake = float(data["brake"])
        steer = float(data["steer"])

        if not 0.0 <= throttle <= 1.0:
            raise ValueError("throttle must be in [0, 1].")
        if not 0.0 <= brake <= 1.0:
            raise ValueError("brake must be in [0, 1].")
        if not -1.0 <= steer <= 1.0:
            raise ValueError("steer must be in [-1, 1].")

        data = {
            "command": command,
            "throttle": throttle,
            "brake": brake,
            "steer": steer,
        }

    else:
        data = {"command": command}

    return create_message(
        ecu="VCU",
        message_type="control",
        data=data,
        sequence=sequence,
        vehicle_id=vehicle_id,
    )


def validate_vcu_control_message(
    message: dict[str, Any],
    expected_vehicle_id: str = "SEV-001",
) -> tuple[bool, str]:
    """Validate the structure/ranges of one VCU control message."""

    if not isinstance(message, dict):
        return False, "message is not an object"

    if message.get("protocol_version") != 1:
        return False, "unsupported protocol_version"

    if message.get("vehicle_id") != expected_vehicle_id:
        return False, "unexpected vehicle_id"

    if str(message.get("ecu", "")).upper() != "VCU":
        return False, "unexpected ECU"

    if message.get("message_type") != "control":
        return False, "message_type is not control"

    if not isinstance(message.get("message_id"), str):
        return False, "message_id missing"

    if not isinstance(message.get("timestamp"), (int, float)):
        return False, "timestamp missing"

    if not isinstance(message.get("sequence"), int) or message.get("sequence") < 1:
        return False, "invalid sequence"

    data = message.get("data")
    if not isinstance(data, dict):
        return False, "data is not an object"

    command = str(data.get("command", "")).strip().lower()
    if command not in VCU_COMMANDS:
        return False, "unsupported command"

    if command == "emergency_brake":
        return True, "ok"

    required = {"throttle", "brake", "steer"}
    if not required.issubset(data.keys()):
        return False, "missing control field"

    try:
        throttle = float(data["throttle"])
        brake = float(data["brake"])
        steer = float(data["steer"])
    except (TypeError, ValueError):
        return False, "non-numeric control value"

    if not 0.0 <= throttle <= 1.0:
        return False, "throttle out of range"
    if not 0.0 <= brake <= 1.0:
        return False, "brake out of range"
    if not -1.0 <= steer <= 1.0:
        return False, "steer out of range"

    return True, "ok"
