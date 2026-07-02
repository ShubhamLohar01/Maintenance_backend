"""Shared test harness.

Endpoints depend on `get_rds` (RDS Postgres) and `get_current_user`. For tests we
swap the RDS session for an in-memory SQLite DB and create just the table(s) under
test (avoids the Postgres-only JSONB columns on other RdsBase models). Auth is
overridden with a stub user; `login_as(**kwargs)` lets a test pick the role/plant.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_rds
from app.auth import get_current_user
from app.main import app
from app.models import (
    BreakdownRecord,
    BreakdownDoc,
    MtAsset,
    MtUser,
    MachineDailyKwh,
    MtFloorUtilityReading,
    MtDeviceToken,
)

# RdsBase tables the suite needs (all SQLite-compatible — no JSONB columns).
_TABLES = [
    BreakdownRecord,
    BreakdownDoc,
    MtAsset,
    MtUser,
    MachineDailyKwh,
    MtFloorUtilityReading,
    MtDeviceToken,
]


class StubUser:
    """Stand-in for an MtUser with the same role/plant properties the endpoints use."""

    def __init__(self, username="tester", role="HEAD", location="A-185", id=1, name="Tester"):
        self.username = username
        self.role = role
        self.location = location
        self.id = id
        self.name = name

    @property
    def norm_role(self) -> str:
        return (self.role or "").strip().upper() or "OPERATOR"

    @property
    def plant_id(self) -> str:
        return (self.location or "UNKNOWN").strip()


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    for model in _TABLES:
        model.__table__.create(bind=engine)
    TestingSession = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, future=True
    )
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def client(db_session):
    def _override_get_rds():
        yield db_session

    app.dependency_overrides[get_rds] = _override_get_rds
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def auth_client(client):
    # Default authenticated caller: a HEAD in A-185 (sees all plants).
    app.dependency_overrides[get_current_user] = lambda: StubUser()
    yield client


@pytest.fixture()
def login_as(client):
    """Return a setter that overrides the current user, e.g.
    `c = login_as(role="OPERATOR", location="W-202")`."""

    def _set(**kwargs):
        app.dependency_overrides[get_current_user] = lambda: StubUser(**kwargs)
        return client

    return _set
