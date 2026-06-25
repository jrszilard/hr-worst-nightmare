"""Idempotent additive migration: add contracts.feedback.

The skill_preferences table is created by create_all on startup; this script
only handles the ALTER for the pre-existing contracts table.

    PYTHONPATH=. python scripts/migrate_job_feedback.py
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
    if "feedback" in cols:
        print("feedback already present — no-op.")
    else:
        conn.execute("ALTER TABLE contracts ADD COLUMN feedback VARCHAR")
        conn.commit()
        print("Added contracts.feedback.")
    conn.close()


if __name__ == "__main__":
    main()
