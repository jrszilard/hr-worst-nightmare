from backend.platforms.ats_registry import Capability
from backend.platforms.resolve.data_tier import resolve_from_data
from backend.platforms.resolve.resolution import ResolutionStatus, ResolutionTier


def test_resolves_engine_fillable_from_apply_option():
    res = resolve_from_data(
        "https://www.linkedin.com/jobs/view/9",
        [{"apply_link": "https://boards.greenhouse.io/acme/jobs/9"}],
    )
    assert res.status is ResolutionStatus.resolved
    assert res.capability is Capability.engine_fillable
    assert res.detected_ats == "greenhouse"
    assert res.resolved_url == "https://boards.greenhouse.io/acme/jobs/9"
    assert res.tier is ResolutionTier.data


def test_resolves_multi_page_from_top_url():
    res = resolve_from_data("https://acme.wd1.myworkdayjobs.com/c/job/9", [])
    assert res.status is ResolutionStatus.resolved
    assert res.capability is Capability.multi_page
    assert res.detected_ats == "workday"
    assert res.resolved_url == "https://acme.wd1.myworkdayjobs.com/c/job/9"


def test_prefers_engine_fillable_over_multi_page():
    res = resolve_from_data(
        "https://acme.wd1.myworkdayjobs.com/c/job/9",
        [{"apply_link": "https://jobs.lever.co/acme/x"}],
    )
    assert res.capability is Capability.engine_fillable
    assert res.detected_ats == "lever"


def test_aggregator_only_is_unresolved():
    res = resolve_from_data(
        "https://www.linkedin.com/jobs/view/9",
        [{"apply_link": "https://www.indeed.com/viewjob?jk=9"}],
    )
    assert res.status is ResolutionStatus.unresolved
    assert res.capability is Capability.manual
    assert res.resolved_url is None
    assert res.tier is ResolutionTier.data
