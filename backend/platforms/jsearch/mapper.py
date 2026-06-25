"""Map JSearch (Google-for-Jobs) postings to the screening spec shape + detect the ATS."""

from __future__ import annotations

from backend.core.skill_extract import extract_skills
from backend.platforms.ats_registry import Capability, classify


def detect_ats(apply_url: str | None, apply_options: list[dict] | None) -> str:
    """Submission channel for an apply URL: 'browser' for engine-fillable ATSs
    (Greenhouse/Lever/Ashby), else 'external'. Direct apply_options are checked first
    because JSearch's top-level link is sometimes an aggregator listing."""
    for opt in apply_options or []:
        if classify(opt.get("apply_link"))[1] is Capability.engine_fillable:
            return "browser"
    return "browser" if classify(apply_url)[1] is Capability.engine_fillable else "external"


def _platform_slug(url: str | None) -> str:
    """ATS slug for storage/UI; engine-fillable ATSs keep their slug, else 'external'."""
    slug, cap = classify(url)
    return slug if cap is Capability.engine_fillable else "external"


def _best_apply_url(job: dict) -> str | None:
    """Prefer a direct engine-fillable apply option, else the top-level apply link."""
    for opt in job.get("apply_options") or []:
        link = opt.get("apply_link")
        if classify(link)[1] is Capability.engine_fillable:
            return link
    return job.get("job_apply_link")


def _location(job: dict) -> str | None:
    parts = [job.get("job_city"), job.get("job_state"), job.get("job_country")]
    label = ", ".join(p for p in parts if p)
    if job.get("job_is_remote"):
        return f"Remote - {label}" if label else "Remote"
    return label or None


def map_jsearch_jobs(payload: dict, *, vocab: list[str]) -> list[dict]:
    """Normalize a JSearch /search response to screening specs (one per posting)."""
    specs: list[dict] = []
    for job in payload.get("data") or []:
        job_id = job.get("job_id")
        title = (job.get("job_title") or "").strip()
        if not job_id or not title:
            continue
        url = _best_apply_url(job)
        description = job.get("job_description") or ""
        specs.append({
            "platform": _platform_slug(url),
            "external_id": f"jsearch:{job_id}",
            "title": title,
            "url": url,
            "description": description,
            "skills_required": extract_skills(f"{title} {description}", vocab),
            "client_questions": None,
            "submission_channel": detect_ats(url, job.get("apply_options")),
            "platform_meta": {
                "company": job.get("employer_name"),
                "location": _location(job),
                "remote": bool(job.get("job_is_remote")),
                "publisher": job.get("job_publisher"),
                "apply_options": job.get("apply_options") or [],
            },
        })
    return specs
