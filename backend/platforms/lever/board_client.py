"""Lever public Postings API client (discovery only, no auth)."""

from __future__ import annotations

_BASE = "https://api.lever.co/v0/postings"


def postings_url(company: str) -> str:
    return f"{_BASE}/{company}?mode=json"


def map_lever_jobs(company: str, payload: list, *, vocab: list[str]) -> list[dict]:
    """Map a Lever postings JSON list to job specs."""
    from backend.core.skill_extract import extract_skills

    specs: list[dict] = []
    for job in payload:
        # A job with no id can't form a stable external_id; skip it rather than KeyError the
        # whole batch (parity with the Greenhouse mapper).
        job_id = job.get("id")
        if job_id is None:
            continue
        description = job.get("descriptionPlain") or ""
        categories = job.get("categories") or {}
        url = job.get("applyUrl") or job.get("hostedUrl")
        specs.append({
            "platform": "lever",
            "external_id": f"{company}:{job_id}",
            "title": job.get("text"),
            "url": url,
            "description": description,
            "skills_required": extract_skills(f"{job.get('text','')} {description}", vocab),
            "client_questions": None,
            "submission_channel": "browser",
            "platform_meta": {
                "ats_vendor": "lever",
                "company": company,
                "location": categories.get("location"),
                "team": categories.get("team"),
            },
        })
    return specs
