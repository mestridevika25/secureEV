"""Database configuration for the SecureEV application layer.

The default database is local SQLite so the project can be brought up quickly
without requiring a separate database server.  Set DATABASE_URL to a
PostgreSQL SQLAlchemy URL for the final deployment environment.
"""

from __future__ import annotations

import os
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./secureev.db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""


def get_db() -> Generator[Session, None, None]:
    """Yield one short-lived database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create missing database tables."""
    from database import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
