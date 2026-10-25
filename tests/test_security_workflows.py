from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from blue_team.integrity_checker import IntegrityChecker
from blue_team.ground_truth_validator import GroundTruthValidator
from blue_team.response_engine import ResponseEngine
from database.db import Base
from database.models import MaintenanceLogRecord, SecurityEventRecord
from digital_twin.ota_manager import OTAManager
from digital_twin.vehicle_state import VehicleState
from red_team.data_integrity_attacks import maintenance_log_manipulation
from red_team.control_injection import ControlInjectionAttacker
from red_team.data_spoofing import DataSpoofingAttacker
from red_team.firmware_attacks import FirmwareAttacker
from network.control_schema import create_vcu_control_message
from network.mqtt_config import VCU_CONTROL
from blue_team.security_gateway import SecurityGateway


TEST_FIRMWARE_KEY = b"secureev-unit-test-key-32-bytes!!"


class NoopPublisher:
    def publish(self, *args, **kwargs) -> bool:
        return True


def test_firmware_signature_rejects_modified_package() -> None:
    checker = IntegrityChecker(TEST_FIRMWARE_KEY)
    package = b"firmware v1"
    signature = checker.sign_firmware_package(package)
    attack = FirmwareAttacker().cloud_update_attack("1.0.1", package, signature)

    assert checker.verify_firmware_signature(package, signature)
    assert not checker.verify_firmware_signature(attack.package, attack.signature)
    assert not IntegrityChecker().verify_firmware_signature(package, signature)

def test_attack_comparison_marks_live_result_and_no_defense_as_counterfactual() -> None:
    from backend.main import SecureEVService

    result = SecureEVService.add_attack_comparison(
        {
            "name": "unauthorized_acceleration",
            "published": True,
            "detected": True,
            "defended": True,
            "defense_reason": "Gateway blocked unauthorized control command.",
        }
    )

    assert result["comparison"]["protected"] == {
        "status": "BLOCKED_OR_MITIGATED",
        "detected": True,
        "defended": True,
        "evidence": "Gateway blocked unauthorized control command.",
    }
    assert result["comparison"]["without_defense"]["status"] == "COUNTERFACTUAL_NOT_RUN"
    assert "could reach downstream" in result["comparison"]["without_defense"]["expected_effect"]
    assert "protections were not disabled" in result["comparison"]["note"]


def test_control_injection_scenarios_are_blocked_by_gateway() -> None:
    attacker = ControlInjectionAttacker(NoopPublisher())
    scenarios = (
        attacker.unauthorized_acceleration(1),
        attacker.out_of_range_control(2),
        attacker.unauthorized_command(3),
    )
    for scenario in scenarios:
        decision = SecurityGateway().inspect(scenario.topic, scenario.message)
        assert not decision.allowed
        assert decision.reason == scenario.expected_reason

    gateway = SecurityGateway()
    accepted = create_vcu_control_message(
        "set_control",
        {"throttle": 0.0, "brake": 0.0, "steer": 0.0},
        sequence=1,
    )
    assert gateway.inspect(VCU_CONTROL, accepted).allowed
    replay = attacker.replay_control(accepted)
    decision = gateway.inspect(replay.topic, replay.message)
    assert not decision.allowed
    assert decision.reason == replay.expected_reason


def test_speed_spoofing_is_deterministic_and_keeps_ground_truth_separate() -> None:
    attacker = DataSpoofingAttacker(NoopPublisher())
    scenario = attacker.speed_spoofing(spoofed_speed_kmh=25.0)
    finding = GroundTruthValidator().validate_message(
        scenario.topic,
        scenario.message,
        carla_ground_truth={"speed_kmh": 0.0, "location": {"x": 0, "y": 0, "z": 0}},
        trusted_battery_soc=80.0,
    )
    assert scenario.expected_value == 25.0
    assert finding.attack_type == "speed_spoofing"
    assert finding.actual_value == 0.0
    assert finding.reported_value == 25.0


def test_unauthorized_acceleration_uses_bounded_traffic_manager_target() -> None:
    from backend.runtime import SecureEVRuntime

    class FakeBridge:
        autopilot_enabled = True
        vehicle = object()

        def get_ground_truth_state(self):
            return {"speed_kmh": 28.0}

        def set_patrol_target_speed(self, target):
            self.target = target

    runtime = SecureEVRuntime()
    runtime.bridge = FakeBridge()
    runtime.autonomous_target_speed_kmh = 28.0
    effect = runtime._start_unauthorized_acceleration()
    assert effect["target_speed_kmh"] <= 35.0
    runtime._run_unauthorized_acceleration(0.0)
    assert runtime.bridge.target == effect["target_speed_kmh"]
    runtime._request_safe_stop()
    runtime._run_unauthorized_acceleration(1.0)
    assert runtime._unauthorized_acceleration is None


def test_telemetry_spoof_scenarios_are_detected_against_trusted_state() -> None:
    attacker = DataSpoofingAttacker(NoopPublisher())
    validator = GroundTruthValidator()
    ground_truth = {
        "speed_kmh": 0.0,
        "location": {"x": 1.0, "y": 2.0, "z": 3.0},
    }
    cases = (
        (
            attacker.speed_spoofing(),
            ground_truth,
            80.0,
        ),
        (
            attacker.battery_soc_spoofing(),
            ground_truth,
            80.0,
        ),
        (
            attacker.gps_spoofing(),
            ground_truth,
            80.0,
        ),
    )
    for scenario, truth, trusted_soc in cases:
        finding = validator.validate_message(
            scenario.topic,
            scenario.message,
            carla_ground_truth=truth,
            trusted_battery_soc=trusted_soc,
        )
        assert finding.detected
        assert finding.attack_type == scenario.name


def test_ota_manager_reverifies_signature_at_install() -> None:
    checker = IntegrityChecker(TEST_FIRMWARE_KEY)
    state = VehicleState(firmware_version="1.0.0")
    ota = OTAManager(state, checker)
    valid_package = b"firmware v1.1"

    ota.stage_update(
        version="1.1.0",
        package_data=valid_package,
        signature=checker.sign_firmware_package(valid_package),
    )
    assert ota.install_update()
    assert state.firmware_version == "1.1.0"

    tampered_package = b"firmware v1.1 tampered"
    ota.stage_update(
        version="9.9.9",
        package_data=tampered_package,
        signature=checker.sign_firmware_package(valid_package),
    )
    assert not ota.install_update()
    assert state.firmware_version == "1.1.0"
    assert ota.update_state == "rejected"


def test_runtime_firmware_attacks_are_rejected_without_carla() -> None:
    from backend.runtime import SecureEVRuntime

    runtime = SecureEVRuntime()
    runtime.running = True
    runtime.publisher = NoopPublisher()
    runtime.integrity_checker = IntegrityChecker(TEST_FIRMWARE_KEY)
    runtime.ota = OTAManager(VehicleState(), runtime.integrity_checker)

    for name in ("cloud_update_attack", "ecu_update_attack"):
        result = runtime.launch_attack(name)
        assert result["published"]
        assert result["detected"]
        assert result["defended"]
        assert runtime.ota.update_state == "rejected"
        assert runtime.ota.current_firmware_version == "1.0.0"


def test_hash_chain_detects_maintenance_record_tampering() -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    first = IntegrityChecker.create_log_entry(
        "1", timestamp, {"inspection": "passed"}, "0" * 64
    )
    second = IntegrityChecker.create_log_entry(
        "2", timestamp, {"inspection": "passed"}, first["record_hash"]
    )
    assert IntegrityChecker.verify_log_chain([first, second])

    finding = maintenance_log_manipulation(first)
    assert finding["name"] == "maintenance_log_manipulation"
    assert not IntegrityChecker.verify_log_chain([first, second])


def test_isolated_or_untrusted_ecu_telemetry_is_not_trusted() -> None:
    @dataclass
    class Finding:
        detected: bool = True
        ecu: str = "VCU"
        attack_type: str = "speed_spoofing"
        severity: str = "HIGH"
        reason: str = "ground-truth mismatch"

    engine = ResponseEngine()
    assert engine.is_ecu_trusted("VCU")
    engine.handle_finding(Finding())
    assert not engine.is_ecu_trusted("VCU")
    engine.clear_runtime_state()
    assert engine.is_ecu_trusted("VCU")

    from backend.runtime import SecureEVRuntime

    emitted: list[dict] = []
    runtime = SecureEVRuntime(event_callback=emitted.append)
    runtime.response_engine = engine
    engine.handle_finding(Finding())
    runtime._on_telemetry_message(
        "secureev/vcu/telemetry",
        {"ecu": "VCU", "message_id": "quarantined-1", "data": {"speed_kmh": 1}},
    )
    assert emitted
    assert emitted[0]["type"] == "telemetry_quarantined"
    assert not any(event["type"] == "telemetry" for event in emitted)

    from backend.main import SecureEVService

    service = SecureEVService()
    service.current_telemetry["VCU"] = {"ecu": "VCU", "data": {"speed_kmh": 180}}
    service._persist_response = lambda event: None
    service.handle_runtime_event(
        {
            "type": "response_action",
            "action": "isolate_ecu",
            "ecu": "VCU",
            "attack_type": "speed_spoofing",
            "severity": "HIGH",
            "executed": True,
        }
    )
    assert "VCU" not in service.current_telemetry


def test_critical_response_is_deduplicated_and_safe_stop_is_latched() -> None:
    @dataclass
    class Finding:
        detected: bool = True
        ecu: str = "TCU"
        attack_type: str = "gps_spoofing"
        severity: str = "CRITICAL"
        reason: str = "ground-truth mismatch"

    brake_requests: list[bool] = []
    engine = ResponseEngine(
        emergency_brake_handler=lambda: brake_requests.append(True) or True,
    )
    assert len(engine.handle_finding(Finding())) == 3
    assert engine.handle_finding(Finding()) == []
    assert brake_requests == [True]

    from backend.runtime import SecureEVRuntime

    runtime = SecureEVRuntime()
    assert runtime._request_safe_stop()
    assert not runtime._allow_pending_command(
        {"data": {"command": "set_control", "throttle": 0.0, "brake": 0.0, "steer": 0.0}}
    )
    assert runtime._allow_pending_command({"data": {"command": "emergency_brake"}})


def test_maintenance_attack_persists_tampering_and_alert(monkeypatch, tmp_path) -> None:
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    import backend.main as backend_main

    engine = create_engine(f"sqlite:///{tmp_path / 'security-test.db'}")
    Base.metadata.create_all(engine)
    test_sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(backend_main, "SessionLocal", test_sessions)

    result = backend_main.service.launch_attack("maintenance_log_manipulation")
    assert result["published"] is True
    assert result["detected"] is True
    assert result["defended"] is True

    with test_sessions() as db:
        record = db.scalar(select(MaintenanceLogRecord))
        event = db.scalar(
            select(SecurityEventRecord).where(
                SecurityEventRecord.event_type == "maintenance_log_integrity"
            )
        )
        assert record is not None
        assert record.data["inspection"] == "passed"
        assert event is not None
        assert event.action == "tampering_detected"

    engine.dispose()
