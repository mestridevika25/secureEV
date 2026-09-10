"""
message_schema.py

Standard message envelope used by SecureEV MQTT communication.

The timestamp + sequence + ECU identity fields are intentionally present now
because later Blue Team controls will use them for freshness, replay, and
message-consistency checks.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from network.mqtt_config import VEHICLE_ID


def create_message(
    ecu: str,
    message_type: str,
    data: dict[str, Any],
    sequence: int,
    vehicle_id: str = VEHICLE_ID,
) -> dict[str, Any]:
    """Create one validated SecureEV MQTT message."""

    ecu = str(ecu).strip().upper()
    message_type = str(message_type).strip().lower()

    if not ecu:
        raise ValueError("ecu cannot be empty.")

    if not message_type:
        raise ValueError("message_type cannot be empty.")

    if not isinstance(data, dict):
        raise TypeError("data must be a dictionary.")

    if int(sequence) < 0:
        raise ValueError("sequence must be >= 0.")

    if not vehicle_id:
        raise ValueError("vehicle_id cannot be empty.")

    return {
        "protocol_version": 1,
        "message_id": str(uuid.uuid4()),
        "vehicle_id": str(vehicle_id),
        "ecu": ecu,
        "message_type": message_type,
        "timestamp": time.time(),
        "sequence": int(sequence),
        "data": data,
    }
