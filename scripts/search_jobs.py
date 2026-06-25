"""Run the JSearch discovery and ingest postings (autonomous/cron path).

    PYTHONPATH=. python scripts/search_jobs.py

Mirrors the Jobs-page "Search jobs" button but runs headless from the terminal. Requires
JSEARCH_API_KEY in .env.
"""

from __future__ import annotations

import asyncio

from backend.api.scanner import _job_skip_threshold
from backend.core.job_search import load_search_config, search_jobs
from backend.platforms.jsearch.client import fetch_jsearch
from backend.db.database import async_session, create_tables


async def main() -> None:
    await create_tables()
    config = load_search_config()
    print(f"Searching: {config.get('queries')}  (remote_only={config.get('remote_only')})")
    async with async_session() as session:
        summary = await search_jobs(
            session, config=config, fetch=fetch_jsearch, threshold=_job_skip_threshold(),
        )
        await session.commit()
    print(f"Done. {summary['total']} ingested, {summary['candidates']} candidate(s), "
          f"{summary['skipped']} skipped.")
    for err in summary.get("errors", []):
        print(f"  ERROR {err}")


if __name__ == "__main__":
    asyncio.run(main())
