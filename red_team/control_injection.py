"""
control_injection.py

SecureEV Phase 6A - controlled Red Team control-injection attacks.

This module creates deliberately malicious VCU control messages for the local
SecureEV lab environment.  It does not call CARLA directly and it does not
bypass the MQTT Security Gateway.

Phase 6A scenarios:
    1. unauthorized_acceleration  -> forged vehicle identity + high throttle
    2. out_of_range_control       -> impossible throttle value
    3. replay_control              -> replay an already accepted packet
    4. unauthorized_command        -> inject an unsupported command

The purpose is to verify that the Phase 5 Security Gateway rejects detectable
control-injection attempts before they reach the VCU.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from network.control_schema import create_vcu_control_message
from network.mqtt_config import VCU_CONTROL, VEHICLE_ID
from network.publisher import MQTTPublisher


@dataclass(frozen=True)
class AttackScenario:
    """One controlled control-injection scenario."""

    name: str
    topic: str
    message: dict[str, Any]
    expected_reason: str
    description: str


class ControlInjectionAttacker:
    """Construct and publish controlled VCU command-injection attempts."""

    def __init__(
        self,
        publisher: MQTTPublisher,
        vehicle_id: str = VEHICLE_ID,
    ) -> None:
        if publisher is None:
            raise ValueError("publisher cannot be None.")
        if not vehicle_id:
            raise ValueError("vehicle_id cannot be empty.")

        self.publisher = publisher
        self.vehicle_id = vehicle_id

    def _base_set_control(self, sequence: int) -> dict[str, Any]:
        return create_vcu_control_message(
            command="set_control",
            data={
                "throttle": 0.0,
                "brake": 0.0,
                "steer": 0.0,
            },
            sequence=sequence,
            vehicle_id=self.vehicle_id,
        )

    def unauthorized_acceleration(self, sequence: int) -> AttackScenario:
        """Forge a command from another vehicle and request full throttle."""
        message = self._base_set_control(sequence)
        message["vehicle_id"] = "ATTACKER-001"
        message["data"].update(
            {
                "throttle": 1.0,
                "brake": 0.0,
                "steer": 0.0,
            }
        )

        return AttackScenario(
            name="unauthorized_acceleration",
            topic=VCU_CONTROL,
            message=message,
            expected_reason="unexpected vehicle_id",
            description="Forged vehicle identity with maximum throttle.",
        )

    def out_of_range_control(self, sequence: int) -> AttackScenario:
        """Inject an impossible throttle value to test range enforcement."""
        message = self._base_set_control(sequence)
        message["data"]["throttle"] = 1.50

        return AttackScenario(
            name="out_of_range_control",
            topic=VCU_CONTROL,
            message=message,
            expected_reason="throttle out of range",
            description="Impossible throttle value intended to bypass limits.",
        )

    def replay_control(self, accepted_message: dict[str, Any]) -> AttackScenario:
        """Replay an already accepted MQTT control packet unchanged."""
        if not isinstance(accepted_message, dict):
            raise TypeError("accepted_message must be a dictionary.")

        message = copy.deepcopy(accepted_message)

        return AttackScenario(
            name="replay_control",
            topic=VCU_CONTROL,
            message=message,
            expected_reason="replay detected",
            description="Re-send a previously accepted control packet.",
        )

    def unauthorized_command(self, sequence: int) -> AttackScenario:
        """Inject a command that is outside the VCU command policy."""
        message = self._base_set_control(sequence)
        message["data"]["command"] = "remote_unlock"
        message["data"].pop("throttle", None)
        message["data"].pop("brake", None)
        message["data"].pop("steer", None)

        return AttackScenario(
            name="unauthorized_command",
            topic=VCU_CONTROL,
            message=message,
            expected_reason="unsupported command",
            description="Inject an unsupported VCU command.",
        )

    def publish_attack(self, scenario: AttackScenario) -> bool:
        """Publish one controlled attack through the normal MQTT path."""
        return self.publisher.publish(
            scenario.topic,
            scenario.message,
            qos=1,
        )
