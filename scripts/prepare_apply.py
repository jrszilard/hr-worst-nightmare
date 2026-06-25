"""Prepare an offline 'apply package' for an in-session Workday assisted apply.

Standalone CLI (run via Bash from a Claude Code session). No browser. Reuses the
backend generation+budget path (exactly once) and the pure Workday URL resolver,
pre-flights + stages the resume/cover-letter into a session-shared directory, and
prints the apply package as JSON to stdout. See the design spec + the apply-workday
skill. Screening answers are NOT here — Workday questions are read live in-session.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core.models import ApplicantInfo  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import selectinload  # noqa: E402

from backend.db.models import OpportunityDB  # noqa: E402
from backend.platforms.form_fill import _extract_company_from_url  # noqa: E402
from backend.core.profile_context import get_profile_context  # noqa: E402
from backend.platforms.workday.url_resolve import is_workday_host, pick_apply_url, to_apply_route  # noqa: E402
from backend.portfolio.profile_loader import get_profile  # noqa: E402
# Staging logic lives in a backend module so both this CLI and the assisted-apply endpoint
# stage to the SAME place. Re-exported here for back-compat with existing callers/tests.
from backend.platforms.apply_staging import (  # noqa: E402,F401
    ResumePreflightError, stage_documents, validate_resume, _resume_source_path,
)

_DEFAULT_OUT_DIR = get_profile_context().apply_artifacts_dir


def build_apply_package(
    *, job_id: int, title: str, cover_letter: str, applicant: ApplicantInfo,
    resolved_url: str | None, url_source: str, resume_path: str,
    cover_letter_pdf_path: str, generated: bool,
) -> dict:
    """Assemble the JSON apply package (offline-knowable parts only)."""
    return {
        "job_id": job_id,
        "resolved_url": resolved_url,
        "url_source": url_source,
        "generated": generated,
        "cover_letter": cover_letter,
        "cover_letter_pdf_path": cover_letter_pdf_path,
        "resume_path": resume_path,
        "applicant": {
            "first_name": applicant.first_name, "last_name": applicant.last_name,
            "email": applicant.email, "phone": applicant.phone,
            "country": applicant.country,
            "work_authorization": applicant.work_authorization,
            "needs_sponsorship": applicant.needs_sponsorship,
            "linkedin": applicant.linkedin, "website": applicant.website,
        },
        "work_history": [w.model_dump() for w in applicant.work_history],
        "education": [e.model_dump() for e in applicant.education],
        "skills": list(applicant.skills),
    }


async def prepare(session, job_id: int, *, out_dir: Path = _DEFAULT_OUT_DIR) -> dict:
    """Build the apply package for *job_id*: ensure generation (once), resolve URL,
    stage documents, assemble package. Does NOT touch a browser."""
    from backend.api.jobs import ensure_application_generated  # lazy: avoids import cost at module load

    job = (await session.execute(
        select(OpportunityDB).options(selectinload(OpportunityDB.job_application))
        .where(OpportunityDB.id == job_id)
    )).scalar_one_or_none()
    if job is None:
        raise SystemExit(f"No job with id {job_id}")

    app, generated = await ensure_application_generated(session, job)

    picked, source = pick_apply_url(None, job.url)
    if picked is None and is_workday_host(job.url):
        picked, source = job.url, "job_apply_link"
    resolved = to_apply_route(picked) if picked else None

    applicant = get_profile().applicant
    company = _extract_company_from_url(job.url)
    resume_path, cl_pdf = stage_documents(applicant, job.title or "", company,
                                          app.cover_letter or "", Path(out_dir))
    return build_apply_package(
        job_id=job.id, title=job.title or "", cover_letter=app.cover_letter or "",
        applicant=applicant, resolved_url=resolved, url_source=source,
        resume_path=resume_path, cover_letter_pdf_path=cl_pdf, generated=generated,
    )


async def _amain(job_id: int, out_dir: Path) -> None:
    from backend.db.database import async_session
    async with async_session() as session:
        pkg = await prepare(session, job_id, out_dir=out_dir)
    print(json.dumps(pkg, indent=2))
    note = "generated + charged" if pkg["generated"] else "reused existing (no charge)"
    print(f"[prepare_apply] job {job_id}: {note}; url_source={pkg['url_source']}", file=sys.stderr)
    if pkg["resolved_url"] is None:
        print("[prepare_apply] No direct Workday URL found — resolve in-session "
              "(follow the aggregator 'Apply on company website' redirect).", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(description="Prepare a Workday apply package (no browser).")
    ap.add_argument("job_id", type=int)
    ap.add_argument("--out-dir", type=Path, default=_DEFAULT_OUT_DIR)
    args = ap.parse_args()
    asyncio.run(_amain(args.job_id, args.out_dir))


if __name__ == "__main__":
    main()
