import pytest

from backend.platforms.ats_registry import Capability
from backend.platforms.resolve.headless_tier import (
    PageState, FakeResolverBrowser, choose_terminal, resolve_headless,
)
from backend.platforms.resolve.resolution import ResolutionStatus, ResolutionTier


def test_choose_terminal_picks_apply_on_company_link():
    state = PageState(
        final_url="https://www.bebee.com/job/123",
        status=200,
        links=[("Save", "https://www.bebee.com/save/123"),
               ("Apply on company website", "https://boards.greenhouse.io/acme/jobs/9")],
    )
    res = choose_terminal(state)
    assert res.status is ResolutionStatus.resolved
    assert res.capability is Capability.engine_fillable
    assert res.detected_ats == "greenhouse"
    assert res.resolved_url == "https://boards.greenhouse.io/acme/jobs/9"
    assert res.tier is ResolutionTier.headless


def test_choose_terminal_classifies_final_url_after_redirect():
    state = PageState(final_url="https://acme.wd5.myworkdayjobs.com/c/job/9", status=200, links=[])
    res = choose_terminal(state)
    assert res.status is ResolutionStatus.resolved
    assert res.capability is Capability.multi_page
    assert res.detected_ats == "workday"


def test_choose_terminal_http_error_is_dead():
    state = PageState(final_url="https://jobs.example.com/expired", status=404, links=[])
    res = choose_terminal(state)
    assert res.status is ResolutionStatus.dead
    assert res.resolved_url is None


def test_choose_terminal_no_known_ats_is_blocked():
    state = PageState(
        final_url="https://careers.point72.com/job/1",
        status=200,
        links=[("Privacy", "https://point72.com/privacy")],
    )
    res = choose_terminal(state)
    assert res.status is ResolutionStatus.blocked
    assert res.capability is Capability.manual


@pytest.mark.asyncio
async def test_resolve_headless_resolves_and_closes_browser():
    state = PageState("https://x.com/j", 200,
                      [("Apply", "https://jobs.lever.co/acme/abc")])
    browser = FakeResolverBrowser(state=state)
    res = await resolve_headless("https://x.com/j", lambda: browser)
    assert res.detected_ats == "lever"
    assert res.status is ResolutionStatus.resolved
    assert browser.closed is True


@pytest.mark.asyncio
async def test_resolve_headless_load_failure_is_blocked_and_closes():
    browser = FakeResolverBrowser(error=TimeoutError("nav timeout"))
    res = await resolve_headless("https://x.com/j", lambda: browser)
    assert res.status is ResolutionStatus.blocked
    assert res.tier is ResolutionTier.headless
    assert browser.closed is True


@pytest.mark.asyncio
async def test_resolve_headless_close_failure_does_not_propagate():
    state = PageState("https://x.com/j", 200, [("Apply", "https://jobs.lever.co/acme/abc")])

    class CloseRaisesBrowser:
        async def load(self, url):
            return state
        async def close(self):
            raise RuntimeError("playwright died")

    res = await resolve_headless("https://x.com/j", lambda: CloseRaisesBrowser())
    assert res.status is ResolutionStatus.resolved   # close failure didn't lose the resolution
    assert res.detected_ats == "lever"


def test_choose_terminal_status_none_falls_through_to_ats_scan():
    # Playwright can return None status for some navigations -> must not be treated as dead.
    state = PageState("https://acme.wd1.myworkdayjobs.com/c/job/9", None, [])
    res = choose_terminal(state)
    assert res.status is ResolutionStatus.resolved
    assert res.detected_ats == "workday"
