"""Tests for the apply orchestration (budget walk)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.core.apply_runner import compute_plan, execute_apply
from backend.db.models import (
    Base, JobApplicationDB, OpportunityDB, OpportunityKind, SpendEventDB, SpendKind,
)


@pytest.fixture()
async def session():
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def _seed_finalists(session):
    a = OpportunityDB(platform="upwork", external_id="a", title="High contract",
                      kind=OpportunityKind.contract, match_score=0.9, description_fit=0.9,
                      connects_cost=40, is_finalist=True)
    b = OpportunityDB(platform="seed", external_id="b", title="Mid job",
                      kind=OpportunityKind.job, match_score=0.7, description_fit=0.7,
                      connects_cost=0, is_finalist=True)
    c = OpportunityDB(platform="upwork", external_id="c", title="Low contract",
                      kind=OpportunityKind.contract, match_score=0.5, description_fit=0.5,
                      connects_cost=40, is_finalist=True)
    session.add_all([a, b, c]); await session.commit()
    return a, b, c


async def test_plan_defers_when_connects_exhausted(session: AsyncSession):
    await _seed_finalists(session)
    # connects cap 60: first contract (40) fits, second (40) does not; job (0) fits.
    plan = await compute_plan(session, now=datetime.now(UTC),
                              connects_cap=60, gen_apps_cap=20, per_run_cap=None)
    titles = [i.title for i in plan.will_process]
    assert "High contract" in titles and "Mid job" in titles
    assert "Low contract" not in titles
    assert any(d.title == "Low contract" for d in plan.deferred)
    assert plan.connects_total == 40


async def test_per_run_cap_limits_count(session: AsyncSession):
    await _seed_finalists(session)
    plan = await compute_plan(session, now=datetime.now(UTC),
                              connects_cap=999, gen_apps_cap=999, per_run_cap=1)
    assert len(plan.will_process) == 1  # only the top-priority finalist


async def test_execute_generates_persists_and_records_spend(session: AsyncSession):
    a, b, c = await _seed_finalists(session)

    async def fake_generate(opp):
        return {"cover_letter": f"cover for {opp.title}",
                "screening_answers": [{"question": "q", "answer": "a"}],
                "review_flags": []}

    result = await execute_apply(session, now=datetime.now(UTC),
                                 connects_cap=60, gen_apps_cap=20, per_run_cap=None,
                                 generate_fn=fake_generate)
    processed_titles = {i.title for i in result.processed}
    assert "High contract" in processed_titles and "Mid job" in processed_titles
    from sqlalchemy import select
    gen = (await session.execute(select(SpendEventDB))).scalars().all()
    assert sum(1 for e in gen if e.kind == SpendKind.generation) == len(result.processed)
    assert sum(e.amount for e in gen if e.kind == SpendKind.connects) == 40
    japp = (await session.execute(
        select(JobApplicationDB).where(JobApplicationDB.opportunity_id == b.id)
    )).scalar_one()
    assert japp.cover_letter == "cover for Mid job"


async def test_rerun_excludes_already_generated_finalists(session: AsyncSession):
    a, b, c = await _seed_finalists(session)

    async def fake_generate(opp):
        return {"cover_letter": "x", "screening_answers": None, "review_flags": [],
                "sections": None, "bid_amount": None, "estimated_duration": None}

    # First run with a generous budget generates the affordable finalists.
    first = await execute_apply(session, now=datetime.now(UTC),
                                connects_cap=999, gen_apps_cap=999, per_run_cap=None,
                                generate_fn=fake_generate)
    assert len(first.processed) == 3
    # Second run: all are already generated, so nothing is re-processed.
    second = await compute_plan(session, now=datetime.now(UTC),
                                connects_cap=999, gen_apps_cap=999, per_run_cap=None)
    assert second.will_process == []
