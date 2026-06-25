import pytest

from backend.platforms.ats_registry import Capability
from backend.platforms.resolve.headless_tier import PageState, FakeResolverBrowser
from backend.platforms.resolve.resolution import ResolutionStatus, ResolutionTier
from backend.platforms.resolve.resolver import resolve_job


@pytest.mark.asyncio
async def test_tier1_data_resolution_short_circuits_no_browser():
    spawned = []
    def make_browser():
        spawned.append(1)
        return FakeResolverBrowser(state=PageState("x", 200, []))
    res = await resolve_job(
        "https://www.linkedin.com/jobs/view/9",
        [{"apply_link": "https://boards.greenhouse.io/acme/jobs/9"}],
        headless=True, make_browser=make_browser,
    )
    assert res.tier is ResolutionTier.data
    assert res.detected_ats == "greenhouse"
    assert spawned == []   # Tier 1 resolved -> no browser spawned


@pytest.mark.asyncio
async def test_falls_through_to_tier2_when_data_unresolved():
    state = PageState("https://www.indeed.com/viewjob?jk=9", 200,
                      [("Apply on company website", "https://acme.wd1.myworkdayjobs.com/c/job/9")])
    res = await resolve_job(
        "https://www.indeed.com/viewjob?jk=9", [],
        headless=True, make_browser=lambda: FakeResolverBrowser(state=state),
    )
    assert res.tier is ResolutionTier.headless
    assert res.capability is Capability.multi_page
    assert res.detected_ats == "workday"


@pytest.mark.asyncio
async def test_headless_false_stops_at_tier1():
    res = await resolve_job("https://www.indeed.com/viewjob?jk=9", [], headless=False)
    assert res.status is ResolutionStatus.unresolved
    assert res.tier is ResolutionTier.data
