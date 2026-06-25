from backend.platforms.ashby.board_client import jobs_url, map_ashby_jobs


def test_ashby_jobs_url():
    assert jobs_url("openai") == "https://api.ashbyhq.com/posting-api/job-board/openai?includeCompensation=true"


def test_map_ashby_jobs_extracts_location_and_skills():
    payload = {"jobs": [{
        "id": "abc",
        "title": "Data Platform Engineer",
        "jobUrl": "https://jobs.ashbyhq.com/acme/abc",
        "applyUrl": "https://jobs.ashbyhq.com/acme/abc/application",
        "location": "San Francisco",
        "workplaceType": "OnSite",
        "isRemote": False,
        "address": {"postalAddress": {"addressCountry": "United States"}},
        "department": "Engineering",
        "team": "Data",
        "employmentType": "FullTime",
        "isListed": True,
        "descriptionHtml": "<p>Build Python and SQL data pipelines.</p>",
    }]}
    specs = map_ashby_jobs("acme", payload, vocab=["Python", "SQL", "Data modeling"])
    assert len(specs) == 1
    spec = specs[0]
    assert spec["platform"] == "ashby"
    assert spec["external_id"] == "acme:abc"
    assert spec["submission_channel"] == "browser"
    assert spec["platform_meta"]["location"] == "San Francisco, United States"
    assert set(spec["skills_required"]) >= {"Python", "SQL"}


def test_map_ashby_jobs_normalizes_us_remote():
    payload = {"jobs": [{
        "id": "remote-1",
        "title": "Analytics Engineer",
        "jobUrl": "https://jobs.ashbyhq.com/acme/remote-1",
        "location": "United States",
        "workplaceType": "Remote",
        "isRemote": True,
        "address": {"postalAddress": {"addressCountry": "United States"}},
        "descriptionPlain": "SQL analytics engineering",
    }]}
    spec = map_ashby_jobs("acme", payload, vocab=["SQL"])[0]
    assert spec["platform_meta"]["location"] == "Remote - United States"


def test_map_ashby_jobs_skips_id_less_jobs():
    # A job with no id can't form a stable external_id; a malformed/partial payload must
    # not KeyError the whole batch (parity with the Greenhouse mapper hardening).
    payload = {"jobs": [
        {"title": "Orphan, no id", "isListed": True, "descriptionPlain": "Python"},
        {"id": "abc", "title": "Has id", "isListed": True,
         "jobUrl": "https://jobs.ashbyhq.com/acme/abc", "descriptionPlain": "SQL"},
    ]}
    specs = map_ashby_jobs("acme", payload, vocab=["Python", "SQL"])
    assert [s["external_id"] for s in specs] == ["acme:abc"]
