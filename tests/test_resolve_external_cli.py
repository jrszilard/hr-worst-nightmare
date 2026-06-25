import pytest

from backend.core.enums import SubmissionChannel
from backend.db.models import OpportunityDB
from backend.platforms.ats_registry import Capability
from backend.platforms.resolve.headless_tier import PageState, FakeResolverBrowser
from backend.platforms.resolve.resolution import ResolutionStatus
from scripts.resolve_external import resolve_unresolved


async def _ext_job(session, ext_id, url, meta=None, channel=SubmissionChannel.external, status=None):
    job = OpportunityDB(platform="external", external_id=ext_id, url=url, title="Analyst",
                        submission_channel=channel, platform_meta=meta, resolution_status=status)
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


@pytest.mark.asyncio
async def test_resolve_unresolved_persists_and_skips_already_resolved(db_session):
    # Tier-1-resolvable via apply_options.
    j1 = await _ext_job(db_session, "jsearch:1", "https://www.linkedin.com/jobs/view/1",
                        meta={"apply_options": [{"apply_link": "https://boards.greenhouse.io/a/jobs/1"}]})
    # Already resolved -> must be skipped.
    j2 = await _ext_job(db_session, "jsearch:2", "https://boards.lever.co/a/x",
                        status=ResolutionStatus.resolved)
    # Tier-2 only (no apply_options) -> resolves via the fake browser to Workday.
    j3 = await _ext_job(db_session, "jsearch:3", "https://www.indeed.com/viewjob?jk=3")

    state = PageState("https://www.indeed.com/viewjob?jk=3", 200,
                      [("Apply on company website", "https://a.wd1.myworkdayjobs.com/c/job/3")])
    results = await resolve_unresolved(
        db_session, limit=50, headless=True, make_browser=lambda: FakeResolverBrowser(state=state),
    )
    assert len(results) == 2   # j1 + j3; j2 skipped

    await db_session.refresh(j1)
    await db_session.refresh(j3)
    assert j1.submission_channel is SubmissionChannel.browser   # engine_fillable flip
    assert j1.detected_ats == "greenhouse"
    assert j3.detected_ats == "workday"
    assert j3.ats_capability is Capability.multi_page
    assert j3.submission_channel is SubmissionChannel.external  # multi_page stays external
