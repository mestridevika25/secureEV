"""SQLAlchemy models for SecureEV telemetry and security records."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from database.db import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TelemetryRecord(Base):
    __tablename__ = "telemetry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    vehicle_id: Mapped[str] = mapped_column(String(64), index=True)
    ecu: Mapped[str] = mapped_column(String(32), index=True)
    topic: Mapped[str] = mapped_column(String(160))
    message_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_timestamp: Mapped[float | None] = mapped_column(Float, nullable=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)


class SecurityEventRecord(Base):
    __tablename__ = "security_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    ecu: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    attack_type: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    action: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON)


class AttackRecord(Base):
    __tablename__ = "attacks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    name: Mapped[str] = mapped_column(String(96), index=True)
    target_ecu: Mapped[str | None] = mapped_column(String(32), nullable=True)
    topic: Mapped[str | None] = mapped_column(String(160), nullable=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON)


class ResponseRecord(Base):
    __tablename__ = "responses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    ecu: Mapped[str] = mapped_column(String(32), index=True)
    attack_type: Mapped[str] = mapped_column(String(96), index=True)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    executed: Mapped[bool]
    reason: Mapped[str] = mapped_column(Text)


class RecoveryRecord(Base):
    __tablename__ = "recovery_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    vehicle_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    restored_ecus: Mapped[list[str]] = mapped_column(JSON)
    details: Mapped[dict[str, Any]] = mapped_column(JSON)
