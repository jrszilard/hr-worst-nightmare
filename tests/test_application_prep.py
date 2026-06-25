import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

import backend.api.jobs as jobs
from backend.core.enums import SpendKind
from backend.db.models import (
    ContractStatus, JobApplicationDB, OpportunityDB, OpportunityKind, SpendEventDB,
)


def _fake_generate_fn(session):
    async def _gen(opp):
        return {"cover_letter": "Hi, Pat here.", "screening_answers": None,
                "review_flags": [], "cost_usd": 0.02}
    return _gen


async def _load(session, jid):
    return (await session.execute(
        select(OpportunityDB).options(selectinload(OpportunityDB.job_application))
        .where(OpportunityDB.id == jid)
    )).scalar_one()


async def test_generate_then_reuse_charges_exactly_once(db_session, monkeypatch):
    monkeypatch.setattr(jobs, "_make_generate_fn", _fake_generate_fn)
    j = OpportunityDB(platform="external", external_id="wd:1", title="Reporting Analyst",
                      kind=OpportunityKind.job, match_score=0.9, description_fit=0.9,
                      status=ContractStatus.reviewed, is_finalist=True,
                      url="https://acme.wd5.myworkdayjobs.com/job/X_R1")
    db_session.add(j); await db_session.flush(); jid = j.id

    job = await _load(db_session, jid)
    app1, gen1 = await jobs.ensure_application_generated(db_session, job)
    assert gen1 is True and app1.cover_letter == "Hi, Pat here."

    job = await _load(db_session, jid)
    app2, gen2 = await jobs.ensure_application_generated(db_session, job)
    assert gen2 is False

    n_gen = await db_session.scalar(
        select(func.count()).select_from(SpendEventDB).where(SpendEventDB.kind == SpendKind.generation))
    n_dollars = await db_session.scalar(
        select(func.count()).select_from(SpendEventDB).where(SpendEventDB.kind == SpendKind.generation_dollars))
    assert n_gen == 1 and n_dollars == 1
