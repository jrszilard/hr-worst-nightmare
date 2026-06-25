from __future__ import annotations

import pytest
from backend.platforms.ats_registry import classify, is_engine_fillable, Capability


@pytest.mark.parametrize("url,slug,cap", [
    ("https://boards.greenhouse.io/acme/jobs/1", "greenhouse", Capability.engine_fillable),
    ("https://job-boards.greenhouse.io/acme/jobs/1", "greenhouse", Capability.engine_fillable),
    ("https://jobs.lever.co/acme/abc", "lever", Capability.engine_fillable),
    ("https://jobs.ashbyhq.com/acme/abc", "ashby", Capability.engine_fillable),
    ("https://acme.wd1.myworkdayjobs.com/careers/job/1", "workday", Capability.multi_page),
    ("https://wd1.myworkdaysite.com/recruiting/wf/Jobs", "workday", Capability.multi_page),
    ("https://careers-acme.icims.com/jobs/1/apply", "icims", Capability.multi_page),
    ("https://jobs.smartrecruiters.com/acme/1", "smartrecruiters", Capability.multi_page),
    ("https://www.linkedin.com/jobs/view/1", "linkedin", Capability.aggregator),
    ("https://www.indeed.com/viewjob?jk=1", "indeed", Capability.aggregator),
    ("https://careers.point72.com/job/1", "unknown", Capability.manual),
    ("https://notgreenhouse.io/jobs/1", "unknown", Capability.manual),
    ("", "unknown", Capability.manual),
    (None, "unknown", Capability.manual),
])
def test_classify(url, slug, cap):
    assert classify(url) == (slug, cap)


def test_is_engine_fillable():
    assert is_engine_fillable("https://jobs.lever.co/acme/x") is True
    assert is_engine_fillable("https://jobs.ashbyhq.com/acme/x") is True
    assert is_engine_fillable("https://acme.wd1.myworkdayjobs.com/x") is False
    assert is_engine_fillable(None) is False


def test_jobs_api_supported_url_uses_registry():
    from backend.api.jobs import _is_supported_assisted_apply_url
    assert _is_supported_assisted_apply_url("https://boards.greenhouse.io/acme/jobs/1") is True
    assert _is_supported_assisted_apply_url("https://jobs.ashbyhq.com/acme/x") is True
    assert _is_supported_assisted_apply_url("https://jobs.lever.co/acme/x") is True
    assert _is_supported_assisted_apply_url("https://acme.wd1.myworkdayjobs.com/x") is False
    assert _is_supported_assisted_apply_url("https://example.com/x") is False
    assert _is_supported_assisted_apply_url(None) is False


def test_first_known_ats_prefers_engine_fillable():
    from backend.platforms.ats_registry import first_known_ats, Capability
    hit = first_known_ats([
        "https://acme.wd1.myworkdayjobs.com/job/1",   # multi_page (seen first)
        "https://boards.greenhouse.io/acme/jobs/9",    # engine_fillable -> wins
    ])
    assert hit == ("https://boards.greenhouse.io/acme/jobs/9", "greenhouse", Capability.engine_fillable)


def test_first_known_ats_falls_back_to_multi_page():
    from backend.platforms.ats_registry import first_known_ats, Capability
    hit = first_known_ats([
        "https://www.linkedin.com/jobs/view/1",        # aggregator -> ignored
        "https://acme.wd1.myworkdayjobs.com/job/1",    # multi_page -> fallback
    ])
    assert hit == ("https://acme.wd1.myworkdayjobs.com/job/1", "workday", Capability.multi_page)


def test_first_known_ats_none_when_only_aggregator_or_unknown():
    from backend.platforms.ats_registry import first_known_ats
    assert first_known_ats(["https://www.indeed.com/x", "https://careers.point72.com/job/1", None]) is None
    assert first_known_ats([]) is None
