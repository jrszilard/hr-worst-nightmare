"""Shared job screening + upsert. Used by the YAML script and board discovery.

A spec is a dict with: platform, external_id, title, url, description,
skills_required, client_questions, submission_channel, platform_meta, and an
optional description_fit. Below the threshold a job is stored skipped; otherwise
a candidate (status=reviewed). No generation here — that is apply-time only.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.enums import ContractStatus, OpportunityKind, SubmissionChannel
from backend.core.job_fit import job_fit_score
from backend.core.matching import calculate_match_score, normalize_skill
from backend.core.models import LoadedProfile
from backend.core.preference_store import PreferenceStore
from backend.core.preferences import biased_priority, preference_bias
from backend.core.scoring import calculate_job_priority
from backend.db.models import JobApplicationDB, OpportunityDB

# Local remote enforcement. JSearch's `remote_jobs_only=true` API filter is unreliable
# (it returns on-site postings anyway), so we re-check remote eligibility here instead of
# trusting the upstream flag. A posting counts as remote-eligible when it is flagged remote,
# or its text signals remote/nationwide and lacks an explicit on-site requirement.
_REMOTE_OK_RE = re.compile(
    r"\b(remote(?:[ -](?:first|friendly|eligible|position|role|opportunity|work|worker))?"
    r"|work(?:ing)? remotely|works? from home|work[ -]from[ -]home|wfh|telecommut\w*"
    r"|fully remote|100% remote|work from anywhere|anywhere in the (?:u\.?s\.?|country)"
    r"|nationwide)\b",
    re.IGNORECASE,
)
_ONSITE_REQ_RE = re.compile(
    r"\b(commutable|on[ -]?site|in[ -]?office|in the office"
    r"|must (?:relocate|reside|live (?:in|near|within)|be (?:located|based)))\b",
    re.IGNORECASE,
)


def _remote_eligible(spec: dict) -> bool:
    """Whether a posting is plausibly remote (or nationwide). Explicit on-site language
    overrides incidental remote keywords; an unflagged posting with neither signal is
    treated as on-site (skip under remote_only)."""
    meta = spec.get("platform_meta") or {}
    if meta.get("remote") is True:
        return True
    text = " ".join(str(x) for x in (
        spec.get("title", ""), spec.get("description", ""), meta.get("location", "")))
    if _ONSITE_REQ_RE.search(text):
        return False
    return bool(_REMOTE_OK_RE.search(text))


# skip_reason values written by this module; anything else is a human decision
# (e.g. "user skip: …", "posting closed …") and must survive re-scans.
_AUTO_SKIP_REASONS = frozenset({"low_fit", "not_remote"})


async def _get_application(session: AsyncSession, opportunity_id: int) -> JobApplicationDB | None:
    return (await session.execute(
        select(JobApplicationDB).where(JobApplicationDB.opportunity_id == opportunity_id)
    )).scalar_one_or_none()


async def screen_and_store(session: AsyncSession, specs: list[dict],
                           profile: LoadedProfile, threshold: float,
                           remote_only: bool = False) -> dict:
    """Screen each spec, upsert by (platform, external_id). Returns a summary dict.

    When remote_only is set, postings that are not remote-eligible are skipped
    (skip_reason='not_remote') regardless of fit — the upstream JSearch remote filter
    can't be trusted, so we enforce it here.
    """
    weights = await PreferenceStore.load_weights(session)
    candidates = skipped = 0
    for spec in specs:
        match = calculate_match_score(spec.get("skills_required") or [], profile)
        # Fall back to a deterministic fit signal when no AI description_fit was
        # provided, so board-scanned jobs rank by real fit instead of the
        # self-referential ~1.0 match_score.
        fit = spec.get("description_fit")
        if fit is None:
            fit = job_fit_score(
                spec.get("title"), spec.get("description"),
                spec.get("skills_required") or [], profile,
            )
        base = calculate_job_priority(match.match_score, fit)
        skills = [normalize_skill(s) for s in (spec.get("skills_required") or [])]
        priority = biased_priority(base, preference_bias(weights, skills))
        is_skip = priority < threshold
        skip_reason = "low_fit" if is_skip else None
        if remote_only and not _remote_eligible(spec):
            is_skip = True
            skip_reason = "not_remote"

        row = (await session.execute(
            select(OpportunityDB).where(
                OpportunityDB.platform == spec["platform"],
                OpportunityDB.external_id == spec["external_id"],
            )
        )).scalar_one_or_none()
        app = None
        if row is not None:
            app = await _get_application(session, row.id)
            if app is not None and app.applied:
                # Applied is terminal: never re-screen or touch the record.
                continue
            if row.skip_reason and row.skip_reason not in _AUTO_SKIP_REASONS:
                # Manual skip: sticky across re-scans.
                skipped += 1
                continue
        else:
            row = OpportunityDB(platform=spec["platform"], external_id=spec["external_id"])
            session.add(row)

        row.title = spec.get("title")
        row.url = spec.get("url")
        row.description = spec.get("description")
        row.skills_required = spec.get("skills_required") or None
        row.client_questions = spec.get("client_questions") or None
        row.kind = OpportunityKind.job
        row.submission_channel = SubmissionChannel(spec.get("submission_channel", "direct"))
        row.platform_meta = spec.get("platform_meta")
        row.match_score = match.match_score
        row.description_fit = fit
        row.roi_score = 0.0
        row.status = ContractStatus.skipped if is_skip else ContractStatus.reviewed
        row.skip_reason = skip_reason
        row.fetched_at = datetime.now(UTC)
        await session.flush()
        if app is not None and not (app.cover_letter or "").strip():
            # Clear only empty shells; generated (paid-for) content is kept.
            await session.delete(app)

        if is_skip:
            skipped += 1
        else:
            candidates += 1
    return {"candidates": candidates, "skipped": skipped, "total": len(specs)}
