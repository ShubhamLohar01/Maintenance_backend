from app.database import LocalBase, RdsBase
from app.models import MachineDailyKwh

# These MUST stay on the local SQLite engine (auth + app-internal).
LOCAL_REQUIRED = {"users", "machines", "floors"}
# These MUST live on the RDS Postgres engine (pgAdmin-visible maintenance data).
# mt_machine_runs was retired on 2026-06-25 — runs now live in mt_machine_daily_kwh.
RDS_REQUIRED = {"mt_asset_list", "mt_machine_daily_kwh"}


def test_local_base_holds_auth_and_internal_tables():
    assert LOCAL_REQUIRED <= set(LocalBase.metadata.tables)


def test_rds_base_holds_maintenance_tables():
    assert RDS_REQUIRED <= set(RdsBase.metadata.tables)


def test_local_and_rds_table_sets_are_disjoint():
    overlap = set(LocalBase.metadata.tables) & set(RdsBase.metadata.tables)
    assert not overlap, f"a table is mapped to both engines: {overlap}"


def test_machine_daily_kwh_has_no_cross_db_fk():
    # operator_id (= str(mt_users.id)) must not carry a FK to a table on the other
    # engine — the runs/readings table is pure RDS with no cross-DB foreign keys.
    assert len(MachineDailyKwh.__table__.c.operator_id.foreign_keys) == 0
    all_fks = [fk for col in MachineDailyKwh.__table__.columns for fk in col.foreign_keys]
    assert all_fks == []
