from backend.platforms.workday.url_resolve import (
    is_workday_host, pick_apply_url, to_apply_route,
)


def test_recognizes_both_host_families():
    assert is_workday_host("https://acme.wd103.myworkdayjobs.com/en-US/External/job/X_R1-2")
    assert is_workday_host("https://wd1.myworkdaysite.com/recruiting/wf/WellsFargoJobs")
    assert not is_workday_host("https://www.linkedin.com/jobs/view/123")
    assert not is_workday_host("https://example.com")
    assert not is_workday_host(None)


def test_pick_prefers_workday_host_over_aggregators_ignoring_is_direct():
    opts = [
        {"publisher": "LinkedIn", "apply_link": "https://www.linkedin.com/jobs/view/1", "is_direct": True},
        {"publisher": "Acme Careers", "apply_link":
            "https://acme.wd5.myworkdayjobs.com/en-US/External/job/Analyst_R194131-1", "is_direct": False},
    ]
    url, source = pick_apply_url(opts, "https://www.indeed.com/viewjob?jk=9")
    assert url == "https://acme.wd5.myworkdayjobs.com/en-US/External/job/Analyst_R194131-1"
    assert source == "apply_options-host-match"


def test_pick_falls_back_to_job_apply_link_then_resolve_in_session():
    url, source = pick_apply_url([], "https://acme.wd5.myworkdayjobs.com/job/Analyst_R1")
    assert source == "job_apply_link"
    url, source = pick_apply_url(
        [{"apply_link": "https://www.ziprecruiter.com/jobs/x"}],
        "https://www.linkedin.com/jobs/view/2",
    )
    assert url is None and source == "resolve-in-session"


def test_to_apply_route_preserves_cell_and_req_suffix():
    desc = "https://ocpgroup.wd103.myworkdayjobs.com/en-US/ocpcareers/job/Spontaneous_JR100080-2"
    assert to_apply_route(desc) == desc + "/apply/autofillWithResume"
    assert to_apply_route(desc, manual=True) == desc + "/apply/applyManually"
    already = desc + "/apply/autofillWithResume"
    assert to_apply_route(already) == already
