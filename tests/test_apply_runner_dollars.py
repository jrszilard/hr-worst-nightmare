import pytest
from datetime import UTC, datetime
from sqlalchemy import select

from backend.core.apply_runner import execute_apply
from backend.core.enums import OpportunityKind, SpendKind, SubmissionChannel
from backend.db.models import OpportunityDB, SpendEventDB


async def _make_finalist_job(session, **kw):
    row = OpportunityDB(
        platform="seed", external_id=kw["external_id"], title=kw.get("title", "T"),
        kind=OpportunityKind.job, is_finalist=True, match_score=0.9,
        description_fit=0.9, connects_cost=0,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


@pytest.mark.asyncio
async def test_execute_apply_records_actual_dollars(db_session):
    await _make_finalist_job(db_session, external_id="d1")

    async def fake_generate(opp):
        return {"cover_letter": "hi", "screening_answers": None, "review_flags": [],
                "cost_usd": 0.18}

    now = datetime.now(UTC)
    await execute_apply(db_session, now=now, connects_cap=100, gen_apps_cap=100,
                        per_run_cap=None, generate_fn=fake_generate, dollars_cap=100.0)

    events = (await db_session.execute(select(SpendEventDB))).scalars().all()
    dollar_events = [e for e in events if e.kind == SpendKind.generation_dollars]
    assert len(dollar_events) == 1
    assert round(dollar_events[0].amount, 2) == 0.18


@pytest.mark.asyncio
async def test_dollar_cap_defers_when_estimate_exhausted(db_session):
    await _make_finalist_job(db_session, external_id="d2", title="A")
    await _make_finalist_job(db_session, external_id="d3", title="B")

    async def fake_generate(opp):
        return {"cover_letter": "x", "screening_answers": None, "review_flags": [],
                "cost_usd": 0.05}

    now = datetime.now(UTC)
    # est_dollars_per_app defaults 0.05; cap 0.05 allows exactly one app.
    result = await execute_apply(db_session, now=now, connects_cap=100, gen_apps_cap=100,
                                 per_run_cap=None, generate_fn=fake_generate, dollars_cap=0.05)
    assert len(result.processed) == 1
    assert any(d.reason == "budget" for d in result.deferred)


@pytest.mark.asyncio
async def test_missing_cost_falls_back_to_estimate(db_session):
    await _make_finalist_job(db_session, external_id="d4")

    async def fake_generate(opp):
        return {"cover_letter": "hi", "screening_answers": None, "review_flags": []}  # no cost_usd

    now = datetime.now(UTC)
    await execute_apply(db_session, now=now, connects_cap=100, gen_apps_cap=100,
                        per_run_cap=None, generate_fn=fake_generate, dollars_cap=100.0)
    events = (await db_session.execute(select(SpendEventDB))).scalars().all()
    dollar_events = [e for e in events if e.kind == SpendKind.generation_dollars]
    assert round(dollar_events[0].amount, 2) == 0.05  # EST_DOLLARS_PER_APP
