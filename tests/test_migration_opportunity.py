"""Tests for the additive opportunity-model migration."""

import sqlite3

from scripts.migrate_opportunity_model import migrate


def _make_old_db(path: str) -> None:
    """Create a minimal pre-migration ``contracts`` table with one row."""
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE contracts ("
        "id INTEGER PRIMARY KEY, platform TEXT, external_id TEXT, "
        "budget_min REAL, budget_max REAL)"
    )
    conn.execute(
        "INSERT INTO contracts (platform, external_id, budget_min) "
        "VALUES ('upwork', 'c1', 2000.0)"
    )
    conn.commit()
    conn.close()


def _columns(path: str) -> set[str]:
    conn = sqlite3.connect(path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(contracts)")}
    conn.close()
    return cols


def test_migration_adds_columns_and_backfills(tmp_path):
    db = str(tmp_path / "contracts.db")
    _make_old_db(db)

    migrate(db)

    cols = _columns(db)
    assert {"kind", "submission_channel", "platform_meta", "review_flags"} <= cols

    conn = sqlite3.connect(db)
    kind, channel = conn.execute(
        "SELECT kind, submission_channel FROM contracts WHERE external_id='c1'"
    ).fetchone()
    budget = conn.execute(
        "SELECT budget_min FROM contracts WHERE external_id='c1'"
    ).fetchone()[0]
    conn.close()
    assert kind == "contract"
    assert channel == "direct"
    assert budget == 2000.0


def test_migration_is_idempotent(tmp_path):
    db = str(tmp_path / "contracts.db")
    _make_old_db(db)
    migrate(db)
    migrate(db)  # second run must not raise
    assert {"kind", "submission_channel"} <= _columns(db)
