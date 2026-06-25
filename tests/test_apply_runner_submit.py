import pytest
from datetime import UTC, datetime
from sqlalchemy import select

from backend.core.apply_runner import execute_apply
from backend.core.enums import OpportunityKind, SubmissionChannel
from backend.core.platform import SubmitResult
from backend.db.models import JobApplicationDB, OpportunityDB


async def _finalist(session, ext, channel):
    row = OpportunityDB(platform="greenhouse", external_id=ext, title="T",
                        kind=OpportunityKind.job, is_finalist=True, match_score=0.9,
                        description_fit=0.9, connects_cost=0, submission_channel=channel)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def _gen(opp):
    return {"cover_letter": "hi", "screening_answers": None, "review_flags": [], "cost_usd": 0.01}


@pytest.mark.asyncio
async def test_auto_channel_submits_and_marks_applied(db_session):
    await _finalist(db_session, "g1", SubmissionChannel.auto)

    async def submit_fn(opp, artifact):
        return SubmitResult(filled=True, submitted=True, detail="submitted")

    now = datetime.now(UTC)
    await execute_apply(db_session, now=now, connects_cap=100, gen_apps_cap=100,
                        per_run_cap=None, generate_fn=_gen, submit_fn=submit_fn)
    app = (await db_session.execute(
        select(JobApplicationDB).join(OpportunityDB).where(OpportunityDB.external_id == "g1"))
    ).scalar_one()
    assert app.applied is True
    assert app.applied_at is not None


@pytest.mark.asyncio
async def test_auto_channel_abort_does_not_mark_applied(db_session):
    await _finalist(db_session, "g2", SubmissionChannel.auto)

    async def submit_fn(opp, artifact):
        return SubmitResult(filled=False, submitted=False, detail="captcha")

    now = datetime.now(UTC)
    result = await execute_apply(db_session, now=now, connects_cap=100, gen_apps_cap=100,
                                 per_run_cap=None, generate_fn=_gen, submit_fn=submit_fn)
    app = (await db_session.execute(
        select(JobApplicationDB).join(OpportunityDB).where(OpportunityDB.external_id == "g2"))
    ).scalar_one()
    assert app.applied is False
    assert any("captcha" in d.reason for d in result.deferred)


@pytest.mark.asyncio
async def test_direct_channel_does_not_submit(db_session):
    await _finalist(db_session, "u1", SubmissionChannel.direct)
    called = {"n": 0}

    async def submit_fn(opp, artifact):
        called["n"] += 1
        return SubmitResult(filled=True, submitted=True)

    now = datetime.now(UTC)
    await execute_apply(db_session, now=now, connects_cap=100, gen_apps_cap=100,
                        per_run_cap=None, generate_fn=_gen, submit_fn=submit_fn)
    app = (await db_session.execute(
        select(JobApplicationDB).join(OpportunityDB).where(OpportunityDB.external_id == "u1"))
    ).scalar_one()
    assert app.applied is False     # direct = fill-and-stop
    assert called["n"] == 0         # submitter never invoked for direct


@pytest.mark.asyncio
async def test_browser_channel_fills_and_awaits_submit(db_session):
    await _finalist(db_session, "b1", SubmissionChannel.browser)

    async def submit_fn(opp, artifact):
        return SubmitResult(filled=True, submitted=False, detail="filled; awaiting human submit")

    now = datetime.now(UTC)
    result = await execute_apply(db_session, now=now, connects_cap=100, gen_apps_cap=100,
                                 per_run_cap=None, generate_fn=_gen, submit_fn=submit_fn)
    app = (await db_session.execute(
        select(JobApplicationDB).join(OpportunityDB).where(OpportunityDB.external_id == "b1"))
    ).scalar_one()
    assert app.applied is False                                   # never auto-mark on browser
    assert [a.id for a in result.awaiting_submit] == [app.opportunity_id]
    assert result.awaiting_submit[0].detail == "filled; awaiting human submit"
    assert not any(d.id == app.opportunity_id for d in result.deferred)


@pytest.mark.asyncio
async def test_browser_channel_fill_error_is_deferred(db_session):
    await _finalist(db_session, "b2", SubmissionChannel.browser)

    async def submit_fn(opp, artifact):
        return SubmitResult(filled=False, submitted=False, detail="error: boom")

    now = datetime.now(UTC)
    result = await execute_apply(db_session, now=now, connects_cap=100, gen_apps_cap=100,
                                 per_run_cap=None, generate_fn=_gen, submit_fn=submit_fn)
    assert result.awaiting_submit == []
    assert any("boom" in d.reason for d in result.deferred)
