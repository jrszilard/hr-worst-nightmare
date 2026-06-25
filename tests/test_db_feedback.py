"""DB-level tests for the feedback column and skill_preferences table."""

import pytest
from sqlalchemy import select

from backend.db.models import OpportunityDB, OpportunityKind, SkillPreferenceDB


@pytest.mark.asyncio
async def test_opportunity_feedback_defaults_null_and_persists(db_session):
    job = OpportunityDB(platform="seed", external_id="fb-1", kind=OpportunityKind.job)
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)
    assert job.feedback is None
    job.feedback = "liked"
    await db_session.commit()
    got = (await db_session.execute(
        select(OpportunityDB).where(OpportunityDB.external_id == "fb-1")
    )).scalar_one()
    assert got.feedback == "liked"


@pytest.mark.asyncio
async def test_skill_preference_row_persists(db_session):
    db_session.add(SkillPreferenceDB(skill="sql", weight=0.5))
    await db_session.commit()
    got = (await db_session.execute(
        select(SkillPreferenceDB).where(SkillPreferenceDB.skill == "sql")
    )).scalar_one()
    assert got.weight == 0.5
