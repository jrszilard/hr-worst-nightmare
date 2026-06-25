import pytest
from sqlalchemy import select

from backend.core.enums import SubmissionChannel
from backend.db.models import OpportunityDB
from backend.platforms.ats_registry import Capability
from backend.platforms.resolve.resolution import Resolution, ResolutionStatus, ResolutionTier
from backend.platforms.resolve.routing import apply_resolution


async def _make_job(session, url, channel=SubmissionChannel.external):
    job = OpportunityDB(platform="external", external_id="jsearch:r1", url=url,
                        title="Data Analyst", submission_channel=channel)
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


@pytest.mark.asyncio
async def test_engine_fillable_flips_channel_and_url(db_session):
    job = await _make_job(db_session, "https://www.linkedin.com/jobs/view/9")
    res = Resolution("https://boards.greenhouse.io/acme/jobs/9", "greenhouse",
                     Capability.engine_fillable, ResolutionStatus.resolved, ResolutionTier.data)
    apply_resolution(job, res)
    await db_session.commit()
    refreshed = (await db_session.execute(select(OpportunityDB).where(OpportunityDB.id == job.id))).scalar_one()
    assert refreshed.submission_channel is SubmissionChannel.browser
    assert refreshed.url == "https://boards.greenhouse.io/acme/jobs/9"
    assert refreshed.detected_ats == "greenhouse"
    assert refreshed.ats_capability == "engine_fillable"
    assert refreshed.resolution_status == "resolved"
    assert refreshed.resolved_url == "https://boards.greenhouse.io/acme/jobs/9"


@pytest.mark.asyncio
async def test_multi_page_stays_external_but_records_ats(db_session):
    job = await _make_job(db_session, "https://acme.wd1.myworkdayjobs.com/c/job/9")
    res = Resolution("https://acme.wd1.myworkdayjobs.com/c/job/9", "workday",
                     Capability.multi_page, ResolutionStatus.resolved, ResolutionTier.data)
    apply_resolution(job, res)
    await db_session.commit()
    assert job.submission_channel is SubmissionChannel.external
    assert job.url == "https://acme.wd1.myworkdayjobs.com/c/job/9"
    assert job.detected_ats == "workday"
    assert job.ats_capability == "multi_page"
    assert job.resolution_status == "resolved"


@pytest.mark.asyncio
async def test_unresolved_records_status_only(db_session):
    job = await _make_job(db_session, "https://www.linkedin.com/jobs/view/9")
    res = Resolution(None, "unknown", Capability.manual, ResolutionStatus.unresolved, ResolutionTier.data)
    apply_resolution(job, res)
    await db_session.commit()
    assert job.submission_channel is SubmissionChannel.external
    assert job.resolution_status == "unresolved"
    assert job.resolved_url is None


def test_resolution_tier_is_an_enum():
    from backend.platforms.resolve.resolution import ResolutionTier
    assert ResolutionTier.data == "data"           # str-enum equality preserved
    assert ResolutionTier("headless") is ResolutionTier.headless


@pytest.mark.asyncio
async def test_resolution_columns_round_trip_as_enums(db_session):
    from backend.platforms.resolve.resolution import ResolutionTier
    job = await _make_job(db_session, "https://www.linkedin.com/jobs/view/9")
    res = Resolution("https://boards.greenhouse.io/acme/jobs/9", "greenhouse",
                     Capability.engine_fillable, ResolutionStatus.resolved, ResolutionTier.data)
    apply_resolution(job, res)
    await db_session.commit()
    refreshed = (await db_session.execute(
        select(OpportunityDB).where(OpportunityDB.id == job.id))).scalar_one()
    # Columns read back as enum members (typed), and still compare equal to their value strings.
    assert refreshed.ats_capability is Capability.engine_fillable
    assert refreshed.resolution_status is ResolutionStatus.resolved
    assert refreshed.resolution_tier is ResolutionTier.data
    assert refreshed.ats_capability == "engine_fillable"
