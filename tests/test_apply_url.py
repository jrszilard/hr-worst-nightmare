from backend.platforms.browser.apply_driver import _to_apply_form_url


def test_ashby_bare_url_gets_application_suffix():
    assert (_to_apply_form_url("https://jobs.ashbyhq.com/openai/abc-123")
            == "https://jobs.ashbyhq.com/openai/abc-123/application")


def test_ashby_url_with_query_is_normalized():
    assert (_to_apply_form_url("https://jobs.ashbyhq.com/notion/abc-123?utm=x")
            == "https://jobs.ashbyhq.com/notion/abc-123/application")


def test_ashby_url_already_application_is_unchanged():
    u = "https://jobs.ashbyhq.com/openai/abc-123/application"
    assert _to_apply_form_url(u) == u


def test_greenhouse_listing_rewritten_to_embed_form():
    # A Greenhouse listing URL is rewritten to the canonical /embed/job_app form so the driver
    # never snapshots a lazy-loaded "Apply for this job" gate (Coinbase #2605).
    u = "https://job-boards.greenhouse.io/twilio/jobs/7551660"
    assert (_to_apply_form_url(u)
            == "https://job-boards.greenhouse.io/embed/job_app?token=7551660&for=twilio&gh_jid=7551660")
