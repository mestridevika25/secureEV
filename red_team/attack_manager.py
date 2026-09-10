"""
attack_manager.py

SecureEV Phase 6A - Red Team attack orchestration.

The AttackManager is intentionally small at this stage.  It keeps the Red
Team side separate from the MQTT transport and provides a repeatable place to
record which controlled attacks were launched and whether they were accepted
by the transport layer.

Security verification remains the responsibility of the Blue Team Security
Gateway in Phase 5.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from red_team.control_injection import AttackScenario, ControlInjectionAttacker


@dataclass(frozen=True)
class AttackRecord:
    """Audit record for one launched Red Team scenario."""

    name: str
    topic: str
    expected_reason: str
    published: bool
    description: str


class AttackManager:
    """Run and record controlled Red Team attack scenarios."""

    def __init__(self, attacker: ControlInjectionAttacker) -> None:
        if attacker is None:
            raise ValueError("attacker cannot be None.")

        self.attacker = attacker
        self.records: list[AttackRecord] = []

    def launch(self, scenario: AttackScenario) -> bool:
        """Publish one attack and retain a local audit record."""
        published = self.attacker.publish_attack(scenario)

        self.records.append(
            AttackRecord(
                name=scenario.name,
                topic=scenario.topic,
                expected_reason=scenario.expected_reason,
                published=published,
                description=scenario.description,
            )
        )

        return published

    def successful_launches(self) -> int:
        return sum(1 for record in self.records if record.published)

    def failed_launches(self) -> int:
        return sum(1 for record in self.records if not record.published)

    def summary(self) -> list[dict[str, Any]]:
        return [
            {
                "name": record.name,
                "topic": record.topic,
                "expected_reason": record.expected_reason,
                "published": record.published,
                "description": record.description,
            }
            for record in self.records
        ]
