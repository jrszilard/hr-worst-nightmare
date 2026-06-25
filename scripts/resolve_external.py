"""Resolve the unresolved `external` job lane to real ATSs and print a distribution report.

    PYTHONPATH=. python scripts/resolve_external.py [--limit N] [--tier data|headless]

--tier data    : Tier 1 only (free, no browser) — re-classify from stored url + apply_options.
--tier headless: Tier 1 then Tier 2 (headless Playwright click-through). Default.
"""
from __future__ import annotations

import argparse
import asyncio
from typing import Callable

from sqlalchemy import or_, select

from backend.core.enums import SubmissionChannel
from backend.db.database import async_session, create_tables
from backend.db.models import OpportunityDB
from backend.platforms.resolve.headless_tier import ResolverBrowser
from backend.platforms.resolve.report import distribution_report
from backend.platforms.resolve.resolution import Resolution, ResolutionStatus
from backend.platforms.resolve.resolver import resolve_job
from backend.platforms.resolve.routing import apply_resolution


def _apply_options(job: OpportunityDB) -> list[dict] | None:
    meta = job.platform_meta
    return meta.get("apply_options") if isinstance(meta, dict) else None


async def resolve_unresolved(
    session,
    *,
    limit: int,
    headless: bool,
    make_browser: Callable[[], ResolverBrowser] | None = None,
) -> list[Resolution]:
    """Resolve unresolved external jobs (status NULL or 'unresolved'), persist each,
    and return the Resolutions. Caller-injected make_browser keeps this testable.
    'blocked' rows are NOT re-run here — they go to the interactive Tier-3 procedure;
    to retry a transient block, reset that row's resolution_status to NULL first."""
    rows = (await session.execute(
        select(OpportunityDB)
        .where(OpportunityDB.submission_channel == SubmissionChannel.external)
        # Only NULL (never attempted) + 'unresolved' rows are re-resolved. 'resolved',
        # 'blocked', 'dead', and 'needs_human' rows are intentionally excluded.
        .where(or_(OpportunityDB.resolution_status.is_(None),
                   OpportunityDB.resolution_status == ResolutionStatus.unresolved))
        .order_by(OpportunityDB.id)
        .limit(limit)
    )).scalars().all()

    results: list[Resolution] = []
    for job in rows:
        res = await resolve_job(job.url, _apply_options(job),
                                headless=headless, make_browser=make_browser)
        apply_resolution(job, res)
        results.append(res)
    await session.commit()
    return results


async def _main(limit: int, tier: str) -> None:
    await create_tables()
    async with async_session() as session:
        results = await resolve_unresolved(session, limit=limit, headless=(tier == "headless"))
    print(distribution_report(results))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=50, help="max jobs to resolve this run")
    parser.add_argument("--tier", choices=["data", "headless"], default="headless")
    args = parser.parse_args()
    asyncio.run(_main(args.limit, args.tier))
