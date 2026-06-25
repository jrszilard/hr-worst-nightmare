"""Greenhouse public Job Board API client.

Discovery only (no auth, board token). Submission is handled separately by the
Playwright filler in Plan 3. The HTTP fetch is injected by the scan orchestrator
so this module stays pure and unit-testable.
"""

from __future__ import annotations

import html
import re

_TAG_RE = re.compile(r"<[^>]+>")
_BASE = "https://boards-api.greenhouse.io/v1/boards"


def jobs_url(board_token: str) -> str:
    return f"{_BASE}/{board_token}/jobs?content=true"


def _plain_text(content: str | None) -> str:
    if not content:
        return ""
    return _TAG_RE.sub("", html.unescape(content)).strip()


def map_greenhouse_jobs(board_token: str, payload: dict, *, vocab: list[str]) -> list[dict]:
    """Map a Greenhouse `/jobs?content=true` payload to job specs."""
    from backend.core.skill_extract import extract_skills
    from backend.platforms.ats_registry import is_engine_fillable

    specs: list[dict] = []
    for job in payload.get("jobs", []):
        # A job needs a stable id for both external_id and the canonical fillable URL. A
        # malformed/partial payload must not KeyError the whole batch — skip the id-less job.
        job_id = job.get("id")
        if job_id is None:
            continue
        description = _plain_text(job.get("content"))
        location = (job.get("location") or {}).get("name")
        # Some companies configure a careers-portal absolute_url (e.g. Pinterest,
        # Instacart). That URL is NOT engine-fillable, so the assisted apply 400s and
        # question discovery reads 0 fields. We know the board token + id, so fall back to
        # the canonical hosted Greenhouse form (keep the portal link as posting_url).
        abs_url = job.get("absolute_url")
        url = abs_url if (abs_url and is_engine_fillable(abs_url)) else \
            f"https://job-boards.greenhouse.io/{board_token}/jobs/{job_id}"
        specs.append({
            "platform": "greenhouse",
            "external_id": f"{board_token}:{job_id}",
            "title": job.get("title"),
            "url": url,
            "description": description,
            "skills_required": extract_skills(f"{job.get('title','')} {description}", vocab),
            "client_questions": None,
            "submission_channel": "browser",
            "platform_meta": {
                "ats_vendor": "greenhouse",
                "company": board_token,
                "location": location,
                "posting_url": abs_url,
            },
        })
    return specs
