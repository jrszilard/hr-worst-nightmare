"""Finalist promotion + listing API (the staging lineup)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Optional

import anthropic
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.ai.application_generator import generate_application
from backend.ai.usage import collect_usage
from backend.config import settings as app_settings
from backend.core.apply_runner import compute_plan, execute_apply
from backend.core.budget_store import get_settings
from backend.core.enums import SubmissionChannel
from backend.core.models import AvailabilityConfig
from backend.core.platform import SubmitResult
from backend.platforms.form_fill import _extract_company_from_url
from backend.core.profile_context import get_profile_context
from backend.platforms.browser.apply_driver import discover_questions, fill_application
from backend.platforms.browser.factory import get_browser_engine
from backend.core.scoring import calculate_job_priority
from backend.db.database import get_session
from backend.db.models import OpportunityDB
from backend.portfolio.case_study_loader import load_all_case_studies
from backend.portfolio.profile_loader import get_profile

logger = logging.getLogger(__name__)

router = APIRouter(tags=["finalists"])


class FinalistBody(BaseModel):
    is_finalist: bool


class FinalistItem(BaseModel):
    id: int
    title: Optional[str] = None
    kind: str
    platform: str
    job_priority: float
    connects_cost: int


@router.post("/api/opportunities/{opp_id}/finalist")
async def set_finalist(opp_id: int, body: FinalistBody,
                       session: AsyncSession = Depends(get_session)) -> dict:
    row = (
        await session.execute(select(OpportunityDB).where(OpportunityDB.id == opp_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    row.is_finalist = body.is_finalist
    await session.commit()
    return {"id": opp_id, "is_finalist": body.is_finalist}


@router.get("/api/finalists")
async def list_finalists(session: AsyncSession = Depends(get_session)) -> list[FinalistItem]:
    rows = (
        await session.execute(
            select(OpportunityDB)
            .where(OpportunityDB.is_finalist.is_(True))
            .order_by(OpportunityDB.id.desc())
        )
    ).scalars().all()
    items: list[FinalistItem] = []
    for r in rows:
        items.append(FinalistItem(
            id=r.id, title=r.title, kind=r.kind.value if hasattr(r.kind, "value") else str(r.kind),
            platform=r.platform,
            job_priority=calculate_job_priority(r.match_score or 0.0, r.description_fit),
            connects_cost=r.connects_cost or 0,
        ))
    return items


class RunBody(BaseModel):
    per_run_max_apps: int | None = None


class TotalsOut(BaseModel):
    connects: float
    generation_apps: float
    generation_dollars: float


class DeferredOut(BaseModel):
    id: int
    title: Optional[str] = None
    reason: str


class AwaitingOut(BaseModel):
    id: int
    title: Optional[str] = None
    detail: str


class PlanOut(BaseModel):
    will_process: list[FinalistItem]
    deferred: list[DeferredOut]
    totals: TotalsOut


class RunOut(BaseModel):
    processed: list[FinalistItem]
    deferred: list[DeferredOut]
    awaiting_submit: list[AwaitingOut] = []
    remaining: TotalsOut


def _caps_from(settings, body: RunBody) -> tuple[int, int, int | None, float]:
    per_run = body.per_run_max_apps if body.per_run_max_apps is not None else settings.per_run_max_apps
    return (settings.connects_per_period, settings.generation_apps_per_period,
            per_run, settings.generation_dollars_per_period)


def _to_item(i) -> FinalistItem:
    return FinalistItem(id=i.id, title=i.title, kind=i.kind, platform=i.platform,
                        job_priority=i.job_priority, connects_cost=i.connects_cost)


async def _discover_client_questions(opp) -> list[str]:
    """Preflight browser-channel ATS forms so generation sees real questions."""
    channel = opp.submission_channel.value if hasattr(opp.submission_channel, "value") else str(opp.submission_channel)
    if channel != SubmissionChannel.browser.value or not opp.url:
        return []
    # Headless preflight avoids interrupting the user before we have generated text. The
    # later assisted fill still runs headed and leaves final submit to the human.
    engine = get_browser_engine(get_profile_context(), headless=True)
    return await discover_questions(engine, url=opp.url)


def _merge_questions(existing: list[str] | None, discovered: list[str]) -> list[str] | None:
    if not discovered:
        return existing
    merged: list[str] = []
    seen: set[str] = set()
    for q in [*(existing or []), *discovered]:
        key = " ".join((q or "").lower().split())
        if key and key not in seen:
            seen.add(key)
            merged.append(q)
    return merged or existing


def _make_generate_fn(session):
    """Build the real generation closure (loads profile + case studies once)."""
    profile = get_profile()
    case_studies = load_all_case_studies()
    availability = AvailabilityConfig()
    client = anthropic.AsyncAnthropic(api_key=app_settings.ANTHROPIC_API_KEY)

    async def _gen(opp):
        try:
            discovered = await _discover_client_questions(opp)
        except Exception:  # noqa: BLE001 — preflight failure should not block generation
            logger.exception("Failed to preflight ATS questions for opportunity %s", getattr(opp, "id", None))
            discovered = []
        merged = _merge_questions(opp.client_questions, discovered)
        if merged != opp.client_questions:
            opp.client_questions = merged
            await session.flush()

        with collect_usage() as acc:
            app = await generate_application(
                opportunity=opp, profile=profile,
                availability=availability, client=client, detailed_case_studies=case_studies,
            )
        return {
            "cover_letter": app.cover_letter,
            "screening_answers": [a.model_dump() for a in (app.screening_answers or [])] or None,
            "review_flags": app.review_flags,
            "sections": [s.model_dump() for s in app.sections] if app.sections else None,
            "bid_amount": app.bid_amount,
            "estimated_duration": app.estimated_duration,
            "cost_usd": acc.cost_usd(),
        }
    return _gen


def _make_submit_fn():
    """Build the submit closure. Greenhouse + Lever share the hosted-form driver."""
    applicant = get_profile().applicant

    async def _submit(opp, artifact) -> SubmitResult:
        if not opp.url or applicant is None:
            return SubmitResult(filled=False, submitted=False, detail="missing url/applicant")
        enriched = {
            **artifact,
            "job_title": opp.title or "",
            "company": _extract_company_from_url(opp.url),
        }
        engine = get_browser_engine(get_profile_context(), headless=False, keep_open=False)
        return await fill_application(engine, url=opp.url, artifact=enriched, applicant=applicant)

    return _submit


@router.post("/api/finalists/plan")
async def plan_apply(body: RunBody, session: AsyncSession = Depends(get_session)) -> PlanOut:
    settings = await get_settings(session)
    connects_cap, gen_cap, per_run, dollars_cap = _caps_from(settings, body)
    plan = await compute_plan(session, now=datetime.now(UTC), connects_cap=connects_cap,
                              gen_apps_cap=gen_cap, per_run_cap=per_run, dollars_cap=dollars_cap)
    return PlanOut(
        will_process=[_to_item(i) for i in plan.will_process],
        deferred=[DeferredOut(id=d.id, title=d.title, reason=d.reason) for d in plan.deferred],
        totals=TotalsOut(connects=plan.connects_total, generation_apps=plan.gen_apps_total,
                         generation_dollars=plan.est_dollars_total),
    )


@router.post("/api/finalists/apply")
async def run_apply(body: RunBody, session: AsyncSession = Depends(get_session)) -> RunOut:
    settings = await get_settings(session)
    connects_cap, gen_cap, per_run, dollars_cap = _caps_from(settings, body)
    generate_fn = _make_generate_fn(session)
    submit_fn = _make_submit_fn()
    result = await execute_apply(session, now=datetime.now(UTC), connects_cap=connects_cap,
                                 gen_apps_cap=gen_cap, per_run_cap=per_run,
                                 generate_fn=generate_fn, dollars_cap=dollars_cap,
                                 submit_fn=submit_fn)
    return RunOut(
        processed=[_to_item(i) for i in result.processed],
        deferred=[DeferredOut(id=d.id, title=d.title, reason=d.reason) for d in result.deferred],
        awaiting_submit=[AwaitingOut(id=a.id, title=a.title, detail=a.detail)
                         for a in result.awaiting_submit],
        remaining=TotalsOut(connects=result.connects_remaining,
                            generation_apps=result.gen_apps_remaining,
                            generation_dollars=0.0),
    )
