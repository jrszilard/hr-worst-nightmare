"""Idempotent additive migration: add contracts.is_finalist + new budget tables.

The new tables (budget_settings, spend_events) are created by create_all on
startup; this script only handles the ALTER for the pre-existing contracts table.

    PYTHONPATH=. python scripts/migrate_finalist_budget.py
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

DB = Path(os.environ.get("PROFILE_DIR", "data")) / "contracts.db"


def main() -> None:
    if not DB.exists():
        print("No data/contracts.db — nothing to migrate (create_all will build it).")
        return
    conn = sqlite3.connect(str(DB))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(contracts)")}
    if "is_finalist" in cols:
        print("is_finalist already present — no-op.")
    else:
        conn.execute("ALTER TABLE contracts ADD COLUMN is_finalist BOOLEAN NOT NULL DEFAULT 0")
        conn.commit()
        print("Added contracts.is_finalist.")
    conn.close()


if __name__ == "__main__":
    main()
