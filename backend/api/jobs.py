"""Jobs API — read-only viewer for screened job-kind opportunities.

Buckets (Skipped / Ready / Applied) are derived here from the presence of a
JobApplicationDB row and its ``applied`` flag — the single source of truth.
``job_priority`` is computed on read (never stored; roi_score stays 0 for jobs).
"""

from __future__ import annotations

from datetime import UTC, datetime
import logging
import re
from typing import Literal, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.core.board_scan import (
    _US_STATE_ABBRS, is_us_location, load_board_config, work_mode_from_location,
)
from backend.core.enums import OpportunityKind, SpendKind, SubmissionChannel
from backend.core.job_search import load_search_config
from backend.core.matching import normalize_skill
from backend.core.preferences import apply_feedback, biased_priority, preference_bias
from backend.core.preference_store import PreferenceStore
from backend.core.scoring import calculate_job_priority
from backend.db.database import get_session
from backend.core.platform import SubmitResult
from backend.db.models import JobApplicationDB, OpportunityDB, SpendEventDB
from backend.platforms.ats_registry import is_engine_fillable
from backend.platforms.resolve.resolution import ResolutionStatus
from backend.platforms.resolve.resolver import resolve_job
from backend.platforms.resolve.routing import apply_resolution
from backend.platforms.form_fill import _extract_company_from_url
from backend.platforms.apply_staging import ResumePreflightError, stage_documents
from backend.core.profile_context import get_profile_context
from backend.platforms.browser.apply_driver import fill_application
from backend.platforms.browser.factory import get_browser_engine
from backend.portfolio.profile_loader import get_profile
from backend.core.apply_runner import EST_DOLLARS_PER_APP, _persist
from backend.core.budget_store import get_settings, period_usage
from backend.api.finalists import _make_generate_fn
from backend.platforms.external_apply import open_posting_for_review

router = APIRouter(prefix="/api/jobs", tags=["jobs"])
logger = logging.getLogger(__name__)

Bucket = Literal["skipped", "candidate", "finalist", "applied"]


def _bucket(job: OpportunityDB) -> Bucket:
    """Skipped (no app + below-threshold) / Candidate / Finalist / Applied.

    Generation now happens only at apply-time, so a job_applications row is no
    longer required to be 'candidate' or 'finalist'. Applied is still driven by
    the application row's ``applied`` flag.
    """
    app = job.job_application
    if app is not None and app.applied:
        return "applied"
    if job.is_finalist:
        return "finalist"
    if job.skip_reason:
        return "skipped"
    return "candidate"


def _company_nudge(job: OpportunityDB) -> float:
    """Bounded negative job_priority nudge for de-prioritized (big-tech) companies.

    Read-time ranking only — never affects the screen-time skip decision, so these
    companies are still stored as candidates (de-prioritized, not excluded).
    """
    cfg = load_search_config()
    listed = {c.strip().lower() for c in (cfg.get("deprioritize_companies") or [])}
    if not listed:
        return 0.0
    company = (_meta_value(job, "company") or "").strip().lower()
    if not company:
        return 0.0
    hit = company in listed or any(re.search(rf"\b{re.escape(name)}\b", company) for name in listed)
    return float(cfg.get("deprioritize_nudge", -0.15)) if hit else 0.0


def _biased_job_priority(job: OpportunityDB, weights: dict[str, float]) -> float:
    base = calculate_job_priority(job.match_score or 0.0, job.description_fit)
    skills = [normalize_skill(s) for s in (job.skills_required or [])]
    biased = biased_priority(base, preference_bias(weights, skills))
    return max(0.0, min(biased + _company_nudge(job), 1.0))


def _meta_value(job: OpportunityDB, key: str) -> str | None:
    meta = job.platform_meta or {}
    if isinstance(meta, dict):
        value = meta.get(key)
        return str(value) if value else None
    return None


def _description_excerpt(description: str | None, limit: int = 360) -> str | None:
    if not description:
        return None
    text = " ".join(description.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _location_criteria() -> dict:
    config = load_board_config()
    return config.get("criteria") or config.get("job_criteria") or {}


def _is_visible_under_current_location_criteria(job: OpportunityDB) -> bool:
    """Hide stale non-US board rows after criteria changes without mutating history."""
    criteria = _location_criteria()
    if not criteria.get("us_only"):
        return True
    if job.platform not in {"greenhouse", "lever"}:
        return True
    return is_us_location(_meta_value(job, "location") or job.client_location)


def _clean_location_segment(part: str) -> str:
    """Strip display noise from one location segment without splitting it.

    Removes parenthetical qualifiers ("(Travel-Required)", "(US/Canada)",
    "(US Only or NS Only)"), leftover "/Canada" tokens, a leading "or ", and
    surrounding punctuation/whitespace. Never splits on commas — that would turn
    "San Francisco, CA" into fragments.
    """
    cleaned = re.sub(r"\s*\([^)]*\)", "", part)            # drop parentheticals
    cleaned = re.sub(r"\s*/\s*Canada\b", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\bCanada\s*/\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"^\s*or\s+", "", cleaned, flags=re.I)  # "..., or Remote" leftovers
    return " ".join(cleaned.split()).strip(" ,;|")


def _work_mode(job: OpportunityDB) -> str:
    return work_mode_from_location(_meta_value(job, "location") or job.client_location)


def _split_top_level_commas(text: str) -> list[str]:
    """Split on commas, but ignore commas inside parentheses.

    "Remote (US Only, or NS Only)" is one location, not two — the comma is part of
    a parenthetical qualifier, so splitting on it produced fragments like "NS Only)".
    """
    parts: list[str] = []
    depth = 0
    cur = ""
    for ch in text:
        if ch == "(":
            depth += 1
            cur += ch
        elif ch == ")":
            depth = max(0, depth - 1)
            cur += ch
        elif ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return [p.strip() for p in parts if p.strip()]


def _segment_to_locations(segment: str) -> list[str]:
    """Split one segment into distinct locations, keeping "City, ST" intact.

    Commas are ambiguous: they separate distinct places ("Canada, US-Remote,
    Chicago") but also bind a city to its state ("San Francisco, CA"). Split on
    top-level commas (never inside parentheses), then re-attach bare 2-letter
    state-abbreviation tokens to the preceding location.
    """
    tokens = _split_top_level_commas(segment)
    locations: list[str] = []
    for tok in tokens:
        if locations and tok.upper() in _US_STATE_ABBRS:
            locations[-1] = f"{locations[-1]}, {tok}"
        else:
            locations.append(tok)
    return locations


def _display_location(job: OpportunityDB) -> str | None:
    location = _meta_value(job, "location") or job.client_location
    criteria = _location_criteria()
    if not location or not criteria.get("us_only") or job.platform not in {"greenhouse", "lever"}:
        return location
    # Boards return multi-office strings like "Remote-Friendly (Travel-Required) |
    # San Francisco, CA | Seattle, WA" or "Remote, Canada; Remote, US". When explicit
    # separators (; | •) are present, commas are intra-location ("Remote, US") and we
    # keep segments whole. Only when commas are the *sole* separator ("Canada,
    # US-Remote, Chicago") do we treat them as a list. Keep US-eligible locations,
    # clean each for display, and dedup preserving order.
    segments = [p.strip() for p in re.split(r"\s*[;|•]\s*", location) if p.strip()]
    units = segments if len(segments) > 1 else _segment_to_locations(location)
    us_parts: list[str] = []
    for loc in units:
        if not is_us_location(loc):
            continue
        display = _clean_location_segment(loc)
        if not display:
            # US-eligible but stripped to nothing (e.g. "Remote (US Only)").
            display = "Remote (US)" if "remote" in loc.lower() else None
        if display and display not in us_parts:
            us_parts.append(display)
    return "; ".join(us_parts) if us_parts else location


class JobListItem(BaseModel):
    id: int
    title: Optional[str] = None
    url: Optional[str] = None
    platform: str
    company: Optional[str] = None
    location: Optional[str] = None
    work_mode: str = "location"
    description_excerpt: Optional[str] = None
    skills_required: Optional[list[str]] = None
    match_score: Optional[float] = None
    description_fit: Optional[float] = None
    job_priority: float
    bucket: Bucket
    is_finalist: bool = False
    applied_at: Optional[datetime] = None
    flag_count: int
    skip_reason: Optional[str] = None
    submission_channel: str = "direct"
    feedback: Optional[str] = None


class ScreeningAnswerOut(BaseModel):
    question: str
    answer: str


class JobApplicationUpdate(BaseModel):
    cover_letter: str
    screening_answers: Optional[list[ScreeningAnswerOut]] = None


class FillPreparedOut(BaseModel):
    filled: bool
    submitted: bool = False
    detail: str


class JobDetail(BaseModel):
    id: int
    title: Optional[str] = None
    url: Optional[str] = None
    platform: str
    company: Optional[str] = None
    location: Optional[str] = None
    work_mode: str = "location"
    description: Optional[str] = None
    description_excerpt: Optional[str] = None
    skills_required: Optional[list[str]] = None
    match_score: Optional[float] = None
    description_fit: Optional[float] = None
    job_priority: float
    bucket: Bucket
    is_finalist: bool = False
    skip_reason: Optional[str] = None
    cover_letter: Optional[str] = None
    screening_answers: Optional[list[ScreeningAnswerOut]] = None
    review_flags: Optional[list[dict]] = None
    generated_at: Optional[datetime] = None
    applied: bool = False
    applied_at: Optional[datetime] = None
    submission_channel: str = "direct"
    feedback: Optional[str] = None


_BUCKET_RANK = {"applied": 3, "finalist": 2, "candidate": 1, "skipped": 0}


def _merge_locations(a: str | None, b: str | None) -> str | None:
    """Union the "; "-joined location labels of two merged rows, order-preserving."""
    parts: list[str] = []
    for label in (a, b):
        for piece in (label or "").split(";"):
            piece = piece.strip()
            if piece and piece not in parts:
                parts.append(piece)
    return "; ".join(parts) if parts else (a or b)


def _dedupe_jobs(items: list[JobListItem]) -> list[JobListItem]:
    """Collapse same company+title rows (the same role posted to many offices).

    Keeps the most-progressed / highest-priority row as representative and merges
    the distinct office locations into it. Rows missing a company or title are left
    untouched (no reliable key to merge on).
    """
    out: list[JobListItem] = []
    index: dict[tuple[str, str], int] = {}
    for it in items:
        company = (it.company or "").strip().lower()
        title = (it.title or "").strip().lower()
        if not company or not title:
            out.append(it)
            continue
        key = (company, title)
        if key not in index:
            index[key] = len(out)
            out.append(it)
            continue
        cur = out[index[key]]
        it_rank = (_BUCKET_RANK.get(it.bucket, 0), it.job_priority)
        cur_rank = (_BUCKET_RANK.get(cur.bucket, 0), cur.job_priority)
        keep, drop = (it, cur) if it_rank > cur_rank else (cur, it)
        keep.location = _merge_locations(keep.location, drop.location)
        out[index[key]] = keep
    return out


@router.get("")
async def list_jobs(
    session: AsyncSession = Depends(get_session),
) -> list[JobListItem]:
    """List all job-kind opportunities with derived bucket + computed priority."""
    result = await session.execute(
        select(OpportunityDB)
        .where(OpportunityDB.kind == OpportunityKind.job)
        .options(selectinload(OpportunityDB.job_application))
        .order_by(OpportunityDB.id.desc())
    )
    jobs = result.scalars().all()
    weights = await PreferenceStore.load_weights(session)

    items: list[JobListItem] = []
    for job in jobs:
        if not _is_visible_under_current_location_criteria(job):
            continue
        app = job.job_application
        items.append(JobListItem(
            id=job.id,
            title=job.title,
            url=job.url,
            platform=job.platform,
            company=_meta_value(job, "company"),
            location=_display_location(job),
            work_mode=_work_mode(job),
            description_excerpt=_description_excerpt(job.description),
            skills_required=job.skills_required,
            match_score=job.match_score,
            description_fit=job.description_fit,
            job_priority=_biased_job_priority(job, weights),
            bucket=_bucket(job),
            is_finalist=job.is_finalist,
            applied_at=app.applied_at if app else None,
            flag_count=len(app.review_flags or []) if app else 0,
            skip_reason=job.skip_reason,
            submission_channel=job.submission_channel.value if hasattr(job.submission_channel, "value") else str(job.submission_channel),
            feedback=job.feedback,
        ))
    return _dedupe_jobs(items)


def _make_apply_engine():
    return get_browser_engine(get_profile_context(), headless=False, keep_open=True)


def _is_supported_assisted_apply_url(url: str | None) -> bool:
    """True when the URL is an engine-fillable hosted form (Greenhouse/Lever/Ashby).
    The example.com placeholder used by seed/test jobs is never fillable."""
    if not url:
        return False
    if (urlparse(url).hostname or "") in {"example.com", "www.example.com"}:
        return False
    return is_engine_fillable(url)


# _extract_company_from_url imported from backend.platforms.form_fill


async def _load_job(session: AsyncSession, job_id: int) -> OpportunityDB:
    """Load a job-kind opportunity with its application, or raise 404."""
    result = await session.execute(
        select(OpportunityDB)
        .where(OpportunityDB.id == job_id)
        .options(selectinload(OpportunityDB.job_application))
    )
    job = result.scalar_one_or_none()
    if job is None or job.kind != OpportunityKind.job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def _detail(job: OpportunityDB, weights: dict[str, float]) -> JobDetail:
    app = job.job_application
    return JobDetail(
        id=job.id,
        title=job.title,
        url=job.url,
        platform=job.platform,
        company=_meta_value(job, "company"),
        location=_display_location(job),
        work_mode=_work_mode(job),
        description=job.description,
        description_excerpt=_description_excerpt(job.description),
        skills_required=job.skills_required,
        match_score=job.match_score,
        description_fit=job.description_fit,
        job_priority=_biased_job_priority(job, weights),
        bucket=_bucket(job),
        is_finalist=job.is_finalist,
        skip_reason=job.skip_reason,
        cover_letter=app.cover_letter if app else None,
        screening_answers=(
            [ScreeningAnswerOut(**a) for a in (app.screening_answers or [])]
            if app and app.screening_answers else None
        ),
        review_flags=app.review_flags if app else None,
        generated_at=app.generated_at if app else None,
        applied=app.applied if app else False,
        applied_at=app.applied_at if app else None,
        submission_channel=job.submission_channel.value if hasattr(job.submission_channel, "value") else str(job.submission_channel),
        feedback=job.feedback,
    )


class AppliedBody(BaseModel):
    applied: bool


@router.get("/{job_id}")
async def get_job(
    job_id: int,
    session: AsyncSession = Depends(get_session),
) -> JobDetail:
    """Return a single job with its generated application (if any)."""
    job = await _load_job(session, job_id)
    weights = await PreferenceStore.load_weights(session)
    return _detail(job, weights)


@router.put("/{job_id}/application")
async def update_job_application(
    job_id: int,
    body: JobApplicationUpdate,
    session: AsyncSession = Depends(get_session),
) -> JobDetail:
    """Edit a prepared job application without regenerating/spending Claude budget."""
    job = await _load_job(session, job_id)
    app = job.job_application
    if app is None:
        app = JobApplicationDB(opportunity_id=job.id, cover_letter="")
        session.add(app)
    app.cover_letter = body.cover_letter
    app.screening_answers = [a.model_dump() for a in (body.screening_answers or [])] or None
    await session.commit()
    weights = await PreferenceStore.load_weights(session)
    await session.refresh(job, attribute_names=["job_application"])
    return _detail(job, weights)


@router.post("/{job_id}/fill")
async def fill_prepared_application(
    job_id: int,
    session: AsyncSession = Depends(get_session),
) -> FillPreparedOut:
    """Run assisted browser fill for an already-prepared application.

    This never clicks final submit; the returned detail should tell the human what remains.
    """
    job = await _load_job(session, job_id)
    app = job.job_application
    applicant = get_profile().applicant
    if app is None or not app.cover_letter:
        raise HTTPException(status_code=400, detail="No prepared application to fill")
    if not _is_supported_assisted_apply_url(job.url):
        raise HTTPException(status_code=400, detail="Unsupported or placeholder job URL")
    if applicant is None:
        raise HTTPException(status_code=400, detail="Missing applicant profile")
    artifact = {
        "cover_letter": app.cover_letter,
        "screening_answers": app.screening_answers,
        "review_flags": app.review_flags or [],
        "job_title": job.title or "",
        "company": _extract_company_from_url(job.url),
    }
    result: SubmitResult = await fill_application(_make_apply_engine(), url=job.url,
                                                   artifact=artifact, applicant=applicant)
    return FillPreparedOut(
        filled=result.filled, submitted=result.submitted, detail=result.detail,
    )


@router.post("/{job_id}/applied")
async def set_applied(
    job_id: int,
    body: AppliedBody,
    session: AsyncSession = Depends(get_session),
) -> JobDetail:
    """Mark a job as applied (or un-apply it). The only mutation in this router."""
    job = await _load_job(session, job_id)
    app = job.job_application
    if app is None:
        raise HTTPException(
            status_code=400,
            detail="Cannot mark a skipped job (no generated application) as applied",
        )
    app.applied = body.applied
    app.applied_at = datetime.now(UTC) if body.applied else None
    await session.commit()
    weights = await PreferenceStore.load_weights(session)
    await session.refresh(job, attribute_names=["job_application"])
    return _detail(job, weights)


class ApplyResult(BaseModel):
    generated: bool
    filled: bool
    submitted: bool = False
    detail: str
    resume_path: str | None = None
    cover_letter_pdf_path: str | None = None


class ResolutionOut(BaseModel):
    resolved_url: Optional[str] = None
    detected_ats: str
    capability: str
    status: str
    tier: str
    needs_human: bool
    submission_channel: str


async def ensure_application_generated(
    session: AsyncSession, job: OpportunityDB
) -> tuple[JobApplicationDB, bool]:
    """Generate+persist+meter this job's application if absent; else reuse it.

    Returns (app, generated_now). Budget is metered EXACTLY ONCE across re-runs:
    when a JobApplicationDB row with a non-empty cover_letter already exists, this
    reuses it and records zero spend. Raises HTTPException(402) on budget exhaustion.
    """
    app = job.job_application
    if app is not None and app.cover_letter:
        return app, False
    now = datetime.now(UTC)
    settings = await get_settings(session)
    _connects, used_apps, used_dollars = await period_usage(session, now)
    if used_apps >= settings.generation_apps_per_period:
        raise HTTPException(status_code=402, detail="Generation app budget exhausted for this period")
    if used_dollars >= settings.generation_dollars_per_period:
        raise HTTPException(status_code=402, detail="Generation dollar budget exhausted for this period")
    generated = await _make_generate_fn(session)(job)
    await _persist(session, job, generated)
    session.add(SpendEventDB(kind=SpendKind.generation, amount=1.0,
                             opportunity_id=job.id, created_at=now))
    cost = generated.get("cost_usd")
    cost = float(cost) if cost is not None else EST_DOLLARS_PER_APP
    session.add(SpendEventDB(kind=SpendKind.generation_dollars, amount=cost,
                             opportunity_id=job.id, created_at=now))
    await session.commit()
    await session.refresh(job, attribute_names=["job_application"])
    return job.job_application, True


@router.post("/{job_id}/apply")
async def apply_job(
    job_id: int,
    session: AsyncSession = Depends(get_session),
) -> ApplyResult:
    """Generate one finalist's application (if needed), then run the keep-open
    assisted fill so the human can review and submit.

    This is the targeted, single-job counterpart to the batch ``/api/finalists/apply``:
    it generates with the same closure (incl. browser-channel question discovery),
    records the same budget spend events, and never clicks final submit — the
    pre-filled browser is left open for human review/captcha/submit.
    """
    job = await _load_job(session, job_id)
    is_external = job.submission_channel == SubmissionChannel.external
    if not is_external and not _is_supported_assisted_apply_url(job.url):
        raise HTTPException(status_code=400, detail="Unsupported or placeholder job URL")
    if is_external and (not job.url or urlparse(job.url).hostname in {"example.com", "www.example.com"}):
        raise HTTPException(status_code=400, detail="No valid posting URL to open")
    applicant = get_profile().applicant
    if applicant is None:
        raise HTTPException(status_code=400, detail="Missing applicant profile")

    app, generated_now = await ensure_application_generated(session, job)

    artifact = {
        "cover_letter": app.cover_letter,
        "screening_answers": app.screening_answers,
        "review_flags": app.review_flags or [],
        "job_title": job.title or "",
        "company": _extract_company_from_url(job.url),
    }
    # Stage the résumé + cover-letter PDF into the shared apply_artifacts dir so the human always
    # has them in the same predictable place to attach (browser extensions can't set a file input,
    # so attachment is always manual). Feeding resume_path into the artifact makes the engine's
    # upload escalation name the staged file. Staging must never block the fill.
    resume_path: str | None = None
    cover_letter_pdf_path: str | None = None
    try:
        resume_path, cover_letter_pdf_path = stage_documents(
            applicant, job.title or "", _extract_company_from_url(job.url),
            app.cover_letter or "", get_profile_context().apply_artifacts_dir,
        )
        artifact["resume_path"] = resume_path
        artifact["cover_letter_pdf_path"] = cover_letter_pdf_path
    except (ResumePreflightError, OSError) as exc:
        logger.warning("document staging failed for job %s: %s", job.id, exc)

    if is_external:
        result = await open_posting_for_review(url=job.url)
    else:
        result = await fill_application(_make_apply_engine(), url=job.url,
                                        artifact=artifact, applicant=applicant)
    return ApplyResult(
        generated=generated_now, filled=result.filled,
        submitted=result.submitted, detail=result.detail,
        resume_path=resume_path, cover_letter_pdf_path=cover_letter_pdf_path,
    )


@router.post("/{job_id}/resolve")
async def resolve_job_endpoint(
    job_id: int,
    session: AsyncSession = Depends(get_session),
) -> ResolutionOut:
    """Resolve one external job's real apply URL + ATS (Tiers 1-2), persist, and
    route engine-fillable results to the browser channel. `needs_human` flags the
    blocked residue for the interactive Tier-3 procedure. Never fills or submits."""
    job = await _load_job(session, job_id)
    apply_options = job.platform_meta.get("apply_options") if isinstance(job.platform_meta, dict) else None
    res = await resolve_job(job.url, apply_options, headless=True)
    apply_resolution(job, res)
    await session.commit()
    await session.refresh(job)
    return ResolutionOut(
        resolved_url=res.resolved_url,
        detected_ats=res.detected_ats,
        capability=res.capability.value,
        status=res.status.value,
        tier=res.tier.value,
        needs_human=res.status is ResolutionStatus.blocked,
        submission_channel=job.submission_channel.value if hasattr(job.submission_channel, "value") else str(job.submission_channel),
    )


class FeedbackBody(BaseModel):
    feedback: Optional[Literal["liked", "disliked"]] = None


@router.post("/{job_id}/feedback")
async def set_feedback(
    job_id: int,
    body: FeedbackBody,
    session: AsyncSession = Depends(get_session),
) -> JobDetail:
    """Like/dislike (or clear) a job; train per-skill preference weights."""
    job = await _load_job(session, job_id)
    old_fb = job.feedback
    new_fb = body.feedback
    if new_fb != old_fb:
        skills = [normalize_skill(s) for s in (job.skills_required or [])]
        weights = await PreferenceStore.load_weights(session)
        weights = apply_feedback(weights, skills, old_fb, new_fb)
        await PreferenceStore.save_weights(session, weights, commit=False)
        job.feedback = new_fb
        await session.commit()  # weights + feedback in one transaction
    weights = await PreferenceStore.load_weights(session)
    await session.refresh(job, attribute_names=["job_application"])
    return _detail(job, weights)
