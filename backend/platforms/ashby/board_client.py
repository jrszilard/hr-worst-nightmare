"""Ashby public job-board API client (discovery only, no auth)."""

from __future__ import annotations

import html
import re

_TAG_RE = re.compile(r"<[^>]+>")
_BASE = "https://api.ashbyhq.com/posting-api/job-board"


def jobs_url(board_name: str) -> str:
    return f"{_BASE}/{board_name}?includeCompensation=true"


def _plain_text(html_text: str | None, fallback: str | None = None) -> str:
    text = html_text or fallback or ""
    return _TAG_RE.sub("", html.unescape(text)).strip()


def _country(job: dict) -> str | None:
    address = job.get("address") or {}
    postal = address.get("postalAddress") or {}
    country = postal.get("addressCountry")
    return str(country) if country else None


def _location(job: dict) -> str | None:
    loc = (job.get("location") or "").strip()
    country = _country(job)
    workplace = (job.get("workplaceType") or "").lower()
    is_remote = job.get("isRemote") is True
    if workplace == "remote" or (is_remote and "remote" in loc.lower()):
        if country and country.lower() in {"united states", "usa", "us"}:
            return "Remote - United States"
        return f"Remote - {loc}" if loc else "Remote"
    if loc and country and country.lower() not in loc.lower():
        return f"{loc}, {country}"
    return loc or country


def map_ashby_jobs(board_name: str, payload: dict, *, vocab: list[str]) -> list[dict]:
    """Map an Ashby job-board payload to job specs."""
    from backend.core.skill_extract import extract_skills

    specs: list[dict] = []
    for job in payload.get("jobs", []) or []:
        if job.get("isListed") is False:
            continue
        # A job with no id can't form a stable external_id; skip it rather than KeyError the
        # whole batch (parity with the Greenhouse mapper).
        job_id = job.get("id")
        if job_id is None:
            continue
        description = _plain_text(job.get("descriptionHtml"), job.get("descriptionPlain"))
        title = job.get("title")
        location = _location(job)
        specs.append({
            "platform": "ashby",
            "external_id": f"{board_name}:{job_id}",
            "title": title,
            "url": job.get("jobUrl") or job.get("applyUrl"),
            "description": description,
            "skills_required": extract_skills(f"{title or ''} {description}", vocab),
            "client_questions": None,
            "submission_channel": "browser",
            "platform_meta": {
                "ats_vendor": "ashby",
                "company": board_name,
                "location": location,
                "team": job.get("team"),
                "department": job.get("department"),
                "employment_type": job.get("employmentType"),
                "workplace_type": job.get("workplaceType"),
                "is_remote": job.get("isRemote"),
            },
        })
    return specs
