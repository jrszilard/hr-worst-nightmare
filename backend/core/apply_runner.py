"""Budget-aware apply orchestration.

`compute_plan` is a dry run (spends nothing) used for the confirmation dialog.
`execute_apply` runs the same walk for real: generate -> persist -> record spend,
stopping when a cap is hit. The submit click itself is NOT performed here — that
is the executor sub-project. Generation is injected via ``generate_fn`` so tests
need no Claude calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Awaitable, Callable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.core.budget import BudgetCaps, EST_DOLLARS_PER_APP, can_afford_next
from backend.core.budget_store import est_dollars, period_usage
from backend.core.enums import OpportunityKind, SpendKind, SubmissionChannel
from backend.core.platform import SubmitResult
from backend.core.scoring import calculate_job_priority
from backend.db.models import (
    JobApplicationDB, OpportunityDB, ProposalDB, SpendEventDB,
)

GenerateFn = Callable[[OpportunityDB], Awaitable[dict]]
SubmitFn = Callable[[OpportunityDB, dict], Awaitable["SubmitResult"]]


@dataclass
class _Item:
    id: int
    title: Optional[str]
    kind: str
    platform: str
    job_priority: float
    connects_cost: int


@dataclass
class _Deferred:
    id: int
    title: Optional[str]
    reason: str


@dataclass
class _AwaitingSubmit:
    id: int
    title: Optional[str]
    detail: str


@dataclass
class PlanResult:
    will_process: list[_Item] = field(default_factory=list)
    deferred: list[_Deferred] = field(default_factory=list)
    connects_total: float = 0.0
    gen_apps_total: float = 0.0

    @property
    def est_dollars_total(self) -> float:
        return est_dollars(self.gen_apps_total)


@dataclass
class RunResult:
    processed: list[_Item] = field(default_factory=list)
    deferred: list[_Deferred] = field(default_factory=list)
    awaiting_submit: list[_AwaitingSubmit] = field(default_factory=list)
    connects_remaining: float = 0.0
    gen_apps_remaining: float = 0.0


async def _load_finalists(session: AsyncSession) -> list[OpportunityDB]:
    rows = (
        await session.execute(
            select(OpportunityDB)
            .where(OpportunityDB.is_finalist.is_(True))
            .options(
                selectinload(OpportunityDB.job_application),
                selectinload(OpportunityDB.proposals),
            )
            .execution_options(populate_existing=True)
        )
    ).scalars().all()
    # Only process finalists that have NOT yet been generated. Jobs get a
    # job_application row at generation time; contracts get a ProposalDB. This
    # makes a re-run pick up only newly-added finalists rather than re-charging
    # budget to regenerate ones already prepared.
    pending: list[OpportunityDB] = []
    for r in rows:
        if r.kind == OpportunityKind.job:
            if r.job_application is not None:
                continue
        elif r.proposals:
            continue
        pending.append(r)
    pending.sort(
        key=lambda r: calculate_job_priority(r.match_score or 0.0, r.description_fit),
        reverse=True,
    )
    return pending


def _item(r: OpportunityDB) -> _Item:
    return _Item(
        id=r.id, title=r.title,
        kind=r.kind.value if hasattr(r.kind, "value") else str(r.kind),
        platform=r.platform,
        job_priority=calculate_job_priority(r.match_score or 0.0, r.description_fit),
        connects_cost=r.connects_cost or 0,
    )


def _walk(finalists: list[OpportunityDB], *, connects_used: float, gen_used: float,
          dollars_used: float, caps: BudgetCaps) -> tuple[list[OpportunityDB], list[_Deferred]]:
    """Return (affordable rows in order, deferred items).

    ``connects_used``/``gen_used``/``dollars_used`` are rolling period totals carried
    in from the ledger. ``run_used`` resets to 0 each call. The dollar gate uses the
    per-app estimate; actual cost is recorded post-generation.
    """
    will: list[OpportunityDB] = []
    deferred: list[_Deferred] = []
    c_used, run_used, d_used = connects_used, 0, dollars_used
    for r in finalists:
        next_connects = float(r.connects_cost or 0)
        if can_afford_next(connects_used=c_used, gen_apps_used=gen_used,
                           per_run_used=run_used, caps=caps, next_connects=next_connects,
                           dollars_used=d_used):
            will.append(r)
            c_used += next_connects
            gen_used += 1
            run_used += 1
            d_used += caps.est_dollars_per_app
        else:
            deferred.append(_Deferred(id=r.id, title=r.title, reason="budget"))
    return will, deferred


async def compute_plan(session: AsyncSession, *, now: datetime, connects_cap: int,
                       gen_apps_cap: int, per_run_cap: int | None,
                       dollars_cap: float = float("inf"),
                       est_dollars_per_app: float = EST_DOLLARS_PER_APP) -> PlanResult:
    finalists = await _load_finalists(session)
    connects_used, gen_used, dollars_used = await period_usage(session, now)
    caps = BudgetCaps(connects_cap=connects_cap, gen_apps_cap=gen_apps_cap,
                      per_run_cap=per_run_cap, dollars_cap=dollars_cap,
                      est_dollars_per_app=est_dollars_per_app)
    will, deferred = _walk(finalists, connects_used=connects_used, gen_used=gen_used,
                           dollars_used=dollars_used, caps=caps)
    result = PlanResult(will_process=[_item(r) for r in will], deferred=deferred)
    result.connects_total = sum(r.connects_cost or 0 for r in will)
    result.gen_apps_total = float(len(will))
    return result


async def _persist(session: AsyncSession, opp: OpportunityDB, generated: dict) -> None:
    if opp.kind == OpportunityKind.job:
        app = (
            await session.execute(
                select(JobApplicationDB).where(JobApplicationDB.opportunity_id == opp.id)
            )
        ).scalar_one_or_none()
        if app is None:
            app = JobApplicationDB(opportunity_id=opp.id)
            session.add(app)
        app.cover_letter = generated.get("cover_letter") or ""
        app.screening_answers = generated.get("screening_answers")
        app.review_flags = generated.get("review_flags") or []
    else:
        proposal = (
            await session.execute(
                select(ProposalDB).where(ProposalDB.contract_id == opp.id)
            )
        ).scalars().first()
        if proposal is None:
            proposal = ProposalDB(contract_id=opp.id)
            session.add(proposal)
        proposal.content = generated.get("cover_letter")
        proposal.sections = generated.get("sections")
        proposal.bid_amount = generated.get("bid_amount")
        proposal.estimated_duration = generated.get("estimated_duration")


async def _mark_job_applied(session: AsyncSession, opp: OpportunityDB, now: datetime) -> None:
    app = (await session.execute(
        select(JobApplicationDB).where(JobApplicationDB.opportunity_id == opp.id)
    )).scalar_one_or_none()
    if app is None:
        app = JobApplicationDB(opportunity_id=opp.id)
        session.add(app)
    app.applied = True
    app.applied_at = now


async def execute_apply(session: AsyncSession, *, now: datetime, connects_cap: int,
                        gen_apps_cap: int, per_run_cap: int | None,
                        generate_fn: GenerateFn,
                        dollars_cap: float = float("inf"),
                        est_dollars_per_app: float = EST_DOLLARS_PER_APP,
                        submit_fn: "SubmitFn | None" = None) -> RunResult:
    finalists = await _load_finalists(session)
    connects_used, gen_used, dollars_used = await period_usage(session, now)
    caps = BudgetCaps(connects_cap=connects_cap, gen_apps_cap=gen_apps_cap,
                      per_run_cap=per_run_cap, dollars_cap=dollars_cap,
                      est_dollars_per_app=est_dollars_per_app)
    will, deferred = _walk(finalists, connects_used=connects_used, gen_used=gen_used,
                           dollars_used=dollars_used, caps=caps)

    processed: list[_Item] = []
    awaiting: list[_AwaitingSubmit] = []
    for r in will:
        try:
            generated = await generate_fn(r)
        except Exception as exc:  # noqa: BLE001 — one failure must not abort the batch
            deferred.append(_Deferred(id=r.id, title=r.title, reason=f"generation_error: {exc}"))
            continue
        await _persist(session, r, generated)
        session.add(SpendEventDB(kind=SpendKind.generation, amount=1.0, opportunity_id=r.id, created_at=now))
        cost = generated.get("cost_usd")
        cost = float(cost) if cost is not None else est_dollars_per_app
        session.add(SpendEventDB(kind=SpendKind.generation_dollars, amount=cost,
                                 opportunity_id=r.id, created_at=now))
        if (r.connects_cost or 0) > 0:
            session.add(SpendEventDB(kind=SpendKind.connects, amount=float(r.connects_cost),
                                     opportunity_id=r.id, created_at=now))

        # Route by channel. auto -> submit + mark applied on success.
        # browser -> assisted fill; filled-but-not-submitted is the expected
        # success (awaiting human submit), never auto-marks Applied.
        # direct -> fill-and-stop, submitter not invoked here.
        if submit_fn is not None and r.submission_channel in (
            SubmissionChannel.auto, SubmissionChannel.browser
        ):
            try:
                sub = await submit_fn(r, generated)
            except Exception as exc:  # noqa: BLE001 — never abort batch on submit failure
                sub = SubmitResult(filled=False, submitted=False, detail=f"submit_error: {exc}")

            if not sub.filled:
                deferred.append(_Deferred(id=r.id, title=r.title,
                                          reason=f"submit_failed: {sub.detail}"))
            elif r.submission_channel == SubmissionChannel.auto and sub.submitted:
                await _mark_job_applied(session, r, now)
            elif r.submission_channel == SubmissionChannel.browser and sub.filled:
                awaiting.append(_AwaitingSubmit(id=r.id, title=r.title, detail=sub.detail))
            else:  # auto, filled but not submitted -> genuine non-completion
                deferred.append(_Deferred(id=r.id, title=r.title,
                                          reason=f"submit_failed: {sub.detail}"))

        processed.append(_item(r))
    await session.commit()

    new_connects, new_gen, _new_dollars = await period_usage(session, now)
    return RunResult(processed=processed, deferred=deferred, awaiting_submit=awaiting,
                     connects_remaining=max(0.0, connects_cap - new_connects),
                     gen_apps_remaining=max(0.0, gen_apps_cap - new_gen))
