"""Fast, dependency-light tests for the Person 2 application-layer contract."""

from __future__ import annotations

from backend.main import app
from database.db import init_db
from database.models import (
    AttackRecord,
    RecoveryRecord,
    ResponseRecord,
    SecurityEventRecord,
    TelemetryRecord,
)


def test_person2_routes_are_present() -> None:
    paths = {route.path for route in app.routes}
    required = {
        "/health",
        "/snapshot",
        "/vehicle/state",
        "/vehicle/telemetry",
        "/ecus",
        "/security/alerts",
        "/security/status",
        "/attacks",
        "/responses",
        "/runtime/status",
        "/runtime/start",
        "/runtime/stop",
        "/runtime/recover",
        "/vehicle/control",
        "/vehicle/emergency-brake",
        "/vehicle/autonomous/start",
        "/vehicle/autonomous/stop",
        "/vehicle/autonomous/replan",
        "/attacks/launch",
        "/camera/frame.jpg",
        "/camera/mjpeg",
        "/reports/summary",
        "/reports/evaluation",
        "/reports/export.json",
        "/reports/export.csv",
        "/history/telemetry",
        "/history/security",
        "/history/attacks",
        "/history/responses",
        "/history/recovery",
        "/ws/live",
    }
    assert required.issubset(paths)


def test_database_tables_initialize() -> None:
    init_db()
    expected = {
        TelemetryRecord.__tablename__,
        SecurityEventRecord.__tablename__,
        AttackRecord.__tablename__,
        ResponseRecord.__tablename__,
        RecoveryRecord.__tablename__,
    }
    from database.db import Base

    assert expected.issubset(Base.metadata.tables.keys())
