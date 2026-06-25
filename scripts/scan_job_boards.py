"""Scan configured Greenhouse/Lever boards and ingest jobs (autonomous/cron path).

    PYTHONPATH=. python scripts/scan_job_boards.py

Mirrors the Jobs-page "Scan job boards" button but runs headless from the terminal —
no Claude Code session or browser needed.
"""

from __future__ import annotations

import asyncio

from backend.api.scanner import _fetch_board, _job_skip_threshold
from backend.core.board_scan import load_board_config, scan_job_boards
from backend.db.database import async_session, create_tables


async def main() -> None:
    await create_tables()
    config = load_board_config()
    print(f"Scanning boards: {config}")
    async with async_session() as session:
        summary = await scan_job_boards(
            session, config=config, fetch=_fetch_board, threshold=_job_skip_threshold(),
        )
        await session.commit()
    criteria_filtered = summary.get("criteria_filtered", 0)
    filter_note = f", {criteria_filtered} filtered by criteria" if criteria_filtered else ""
    print(f"Done. {summary['total']} ingested, "
          f"{summary['candidates']} candidate(s), {summary['skipped']} skipped"
          f"{filter_note}.")
    for err in summary.get("errors", []):
        print(f"  ERROR {err}")


if __name__ == "__main__":
    asyncio.run(main())
