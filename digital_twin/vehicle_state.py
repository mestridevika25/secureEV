"""
vehicle_state.py

Phase 2 — Vehicle State Model (single source of truth)

RULE: every field here is OWNED by exactly one ECU. No other module should
write to a field it doesn't own. This is what stops the project from turning
into "a dashboard with fake disconnected numbers."

Ownership (fill in as each ECU is built):
    speed, acceleration        -> VCU  (backed by CarlaBridge ground truth)
    doors, locks                -> BCM
    battery_soc, battery_temp   -> BMS
    motor_temp, motor_rpm       -> MCU
    reported_gps                -> TCU (can diverge from CARLA's real position
                                         under a data-spoofing attack)
    autonomous_mode, planned_*  -> ACU (self-driving control commands)
    charging_state, charge_port_locked,
    vehicle_disabled_flag       -> Charging Controller
    camera_feed_source          -> Camera module (live vs replayed)
    firmware_version             -> OTA Manager

NOT YET IMPLEMENTED. This is a placeholder for Phase 2.
"""

from dataclasses import dataclass, field
from typing import Optional
import time


@dataclass
class VehicleState:
    # Owned by VCU (mirrors CarlaBridge ground truth unless a control-injection
    # attack has altered CARLA's real physics)
    speed_kmh: float = 0.0
    acceleration: float = 0.0

    # Owned by BCM
    doors_locked: bool = True
    doors_open: bool = False

    # Owned by BMS
    battery_soc: float = 100.0
    battery_temp: float = 25.0

    # Owned by MCU
    motor_temp: float = 25.0
    motor_rpm: float = 0.0

    # Owned by TCU — this is the field that can be falsified by GPS spoofing,
    # while CarlaBridge.get_ground_truth_state() keeps reporting the real position
    reported_gps: Optional[dict] = None

    # Owned by ACU
    autonomous_mode: bool = False
    planned_steer: float = 0.0
    planned_throttle: float = 0.0
    planned_brake: float = 0.0

    # Owned by Charging Controller
    charging_state: str = "idle"  # idle | charging | fault
    charge_port_locked: bool = True
    vehicle_disabled_flag: bool = False  # set true by a vehicle_flag_via_charging attack

    # Owned by Camera module
    camera_feed_source: str = "live"  # live | replayed

    # Owned by OTA Manager
    firmware_version: str = "1.0.0"

    last_updated: float = field(default_factory=time.time)