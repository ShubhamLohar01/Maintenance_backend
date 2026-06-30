from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session
from .config import settings


# --- Local SQLite engine: auth + app-internal tables ---
_local_connect_args = (
    {"check_same_thread": False}
    if settings.local_database_url.startswith("sqlite")
    else {}
)
local_engine = create_engine(
    settings.local_database_url, connect_args=_local_connect_args, future=True
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=local_engine, future=True)


# --- RDS Postgres engine: maintenance tables (visible in pgAdmin) ---
# RDS (and any NAT/tunnel in between) silently drops idle connections, so a pooled
# connection can be dead by the next request -> "server closed the connection
# unexpectedly". pool_pre_ping checks liveness and transparently reconnects before
# each use; pool_recycle retires connections before the server's idle timeout; the
# libpq keepalives keep otherwise-idle TCP sockets alive.
rds_engine = create_engine(
    settings.rds_database_url,
    future=True,
    pool_pre_ping=True,
    pool_recycle=1800,  # seconds; recycle before typical RDS/NAT idle cutoffs
    connect_args={
        "connect_timeout": 10,
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 5,
    },
)
SessionRds = sessionmaker(autocommit=False, autoflush=False, bind=rds_engine, future=True)


class LocalBase(DeclarativeBase):
    """Tables that live in the local SQLite DB (auth + app-internal)."""
    pass


class RdsBase(DeclarativeBase):
    """Tables that live in the RDS Postgres DB (maintenance, pgAdmin-visible)."""
    pass


def get_db():
    """SQLite session — auth and app-internal data."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_rds():
    """RDS Postgres session — maintenance tables (runs, readings, assets)."""
    db: Session = SessionRds()
    try:
        yield db
    finally:
        db.close()
