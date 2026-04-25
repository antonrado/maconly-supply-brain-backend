from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.models.base import Base


# In-memory SQLite shared across connections
engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    future=True,
)
SessionTesting = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="session", autouse=True)
def disable_monitoring_scheduler() -> Generator[None, None, None]:
    original_value = os.environ.get("MONITORING_SCHEDULER_ENABLED")
    os.environ["MONITORING_SCHEDULER_ENABLED"] = "false"
    try:
        yield
    finally:
        if original_value is None:
            os.environ.pop("MONITORING_SCHEDULER_ENABLED", None)
        else:
            os.environ["MONITORING_SCHEDULER_ENABLED"] = original_value


@pytest.fixture(scope="session", autouse=True)
def create_test_database() -> Generator[None, None, None]:
    """Create/drop all tables once per test session."""
    Base.metadata.create_all(bind=engine)
    try:
        yield
    finally:
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session() -> Generator:
    """Provide a transactional SQLAlchemy Session for each test.

    Each test runs in its own transaction which is rolled back afterwards,
    so DB state is isolated between tests.
    """
    connection = engine.connect()
    trans = connection.begin()
    session = SessionTesting(bind=connection)
    try:
        yield session
    finally:
        session.close()
        trans.rollback()
        connection.close()
