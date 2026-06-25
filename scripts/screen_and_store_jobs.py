"""Screen jobs from data/jobs_to_screen.yaml and persist them for the UI.

For each job: compute match + job_priority. Below the auto_skip_threshold the
job is stored as 'skipped' (no application). Otherwise it is stored as a
candidate (status=reviewed, no application generated). Generation is deferred
to apply-time for finalists only (see backend/core/apply_runner.py).
Idempotent: upserts by (platform, external_id). No Claude calls; fast + cheap.

    PYTHONPATH=. python scripts/screen_and_store_jobs.py
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import yaml

from backend.core.job_screening import screen_and_store
from backend.core.profile_context import get_profile_context
from backend.db.database import async_session, create_tables
from backend.portfolio.profile_loader import get_profile

INBOX = get_profile_context().jobs_to_screen_yaml


def auto_skip_threshold() -> float:
    profile_yaml = get_profile_context().profile_yaml
    data = yaml.safe_load(profile_yaml.read_text(encoding="utf-8"))
    return float(data.get("auto_skip_threshold", 0.15))


async def main() -> None:
    await create_tables()
    specs = yaml.safe_load(INBOX.read_text(encoding="utf-8")) or []
    profile = get_profile()
    threshold = auto_skip_threshold()
    print(f"Screening {len(specs)} job(s); auto_skip_threshold={threshold}")

    # Normalize YAML specs to the screening contract (defaults for channel/meta).
    for spec in specs:
        spec.setdefault("submission_channel", "direct")
        spec.setdefault("platform_meta", None)

    async with async_session() as session:
        summary = await screen_and_store(session, specs, profile, threshold)
        await session.commit()
    print(f"Done. {summary['candidates']} candidate(s), {summary['skipped']} skipped.")


if __name__ == "__main__":
    asyncio.run(main())
