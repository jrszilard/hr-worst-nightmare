"""Tests for the JobApplicationDB ORM model."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.db.models import Base, JobApplicationDB, OpportunityDB, OpportunityKind


@pytest.fixture()
async def session():
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def test_job_application_persists_and_links_to_opportunity(session: AsyncSession):
    job = OpportunityDB(
        platform="seed", external_id="job-1", title="AI Engineer",
        kind=OpportunityKind.job, match_score=0.6, description_fit=0.9,
    )
    session.add(job)
    await session.flush()

    app = JobApplicationDB(
        opportunity_id=job.id,
        cover_letter="Hello, I am Pat.",
        screening_answers=[{"question": "Why?", "answer": "Because."}],
        review_flags=[{"type": "ai_tell", "detail": "cliché: leverage"}],
        applied=False,
    )
    session.add(app)
    await session.commit()

    loaded = (
        await session.execute(
            select(JobApplicationDB).where(JobApplicationDB.opportunity_id == job.id)
        )
    ).scalar_one()
    assert loaded.cover_letter == "Hello, I am Pat."
    assert loaded.screening_answers[0]["answer"] == "Because."
    assert loaded.applied is False
    assert loaded.applied_at is None


async def test_default_applied_is_false_and_generated_at_set(session: AsyncSession):
    job = OpportunityDB(platform="seed", external_id="job-2", kind=OpportunityKind.job)
    session.add(job)
    await session.flush()
    app = JobApplicationDB(opportunity_id=job.id, cover_letter="Hi")
    session.add(app)
    await session.commit()
    assert app.applied is False
    assert isinstance(app.generated_at, datetime)


async def test_duplicate_opportunity_id_raises(session: AsyncSession):
    job = OpportunityDB(platform="seed", external_id="job-3", kind=OpportunityKind.job)
    session.add(job)
    await session.flush()
    session.add(JobApplicationDB(opportunity_id=job.id, cover_letter="A"))
    await session.commit()
    session.add(JobApplicationDB(opportunity_id=job.id, cover_letter="B"))
    with pytest.raises(Exception):  # IntegrityError on the unique opportunity_id
        await session.commit()
