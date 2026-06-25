#!/usr/bin/env python
"""Additive, idempotent migration: generalise ``contracts`` to opportunities.

Adds kind / submission_channel / platform_meta / review_flags columns and
backfills existing rows to contract/direct. Safe to run repeatedly. The
existing data/contracts.db.bak-* file is the rollback artifact.

Usage:
    python scripts/migrate_opportunity_model.py [path/to/contracts.db]
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

# column name -> SQLite column definition (with default)
_NEW_COLUMNS: dict[str, str] = {
    "kind": "TEXT NOT NULL DEFAULT 'contract'",
    "submission_channel": "TEXT NOT NULL DEFAULT 'direct'",
    "platform_meta": "JSON",
    "review_flags": "JSON",
}

_DEFAULT_DB = str(Path(os.environ.get("PROFILE_DIR", "data")) / "contracts.db")


def _existing_columns(conn: sqlite3.Connection) -> set[str]:
    return {row[1] for row in conn.execute("PRAGMA table_info(contracts)")}


def migrate(db_path: str = _DEFAULT_DB) -> None:
    """Apply the additive migration to *db_path*. Idempotent; never destructive."""
    conn = sqlite3.connect(db_path)
    try:
        cols = _existing_columns(conn)
        if not cols:
            raise SystemExit(
                f"ERROR: no 'contracts' table found in {db_path}; refusing to migrate."
            )

        added: list[str] = []
        for name, ddl in _NEW_COLUMNS.items():
            if name not in cols:
                conn.execute(f"ALTER TABLE contracts ADD COLUMN {name} {ddl}")
                added.append(name)

        conn.execute("UPDATE contracts SET kind='contract' WHERE kind IS NULL")
        conn.execute(
            "UPDATE contracts SET submission_channel='direct' "
            "WHERE submission_channel IS NULL"
        )
        conn.commit()

        if added:
            print(f"Added columns: {', '.join(added)}")
        else:
            print("No new columns needed; schema already up to date.")
        print("Backfill complete.")
    finally:
        conn.close()


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else _DEFAULT_DB
    migrate(target)
