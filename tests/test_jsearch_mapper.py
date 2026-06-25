import pytest
from backend.platforms.jsearch.mapper import detect_ats


@pytest.mark.parametrize("url,expected", [
    ("https://boards.greenhouse.io/acme/jobs/123", "browser"),
    ("https://job-boards.greenhouse.io/acme/jobs/123", "browser"),
    ("https://jobs.lever.co/acme/abc-123", "browser"),
    ("https://jobs.ashbyhq.com/acme/abc-123", "browser"),
    ("https://acme.wd1.myworkdayjobs.com/careers/job/123", "external"),
    ("https://careers-acme.icims.com/jobs/123/apply", "external"),
    ("https://www.linkedin.com/jobs/view/123", "external"),
    ("", "external"),
    (None, "external"),
    # Regression: host-suffix false positive — notgreenhouse.io ends with greenhouse.io
    # but is NOT a greenhouse subdomain and must not be detected as ATS.
    ("https://notgreenhouse.io/jobs/1", "external"),
])
def test_detect_ats_from_url(url, expected):
    assert detect_ats(url, apply_options=None) == expected


def test_detect_ats_prefers_direct_apply_option():
    # The top-level link is a LinkedIn listing, but a direct Greenhouse apply option exists.
    options = [
        {"publisher": "LinkedIn", "apply_link": "https://www.linkedin.com/jobs/view/9", "is_direct": False},
        {"publisher": "Greenhouse", "apply_link": "https://boards.greenhouse.io/acme/jobs/9", "is_direct": True},
    ]
    assert detect_ats("https://www.linkedin.com/jobs/view/9", apply_options=options) == "browser"


# tests/test_jsearch_mapper.py  (append)
from backend.platforms.jsearch.mapper import map_jsearch_jobs

_PAYLOAD = {
    "status": "OK",
    "data": [
        {
            "job_id": "abc123",
            "employer_name": "Wire Belt Co",
            "job_title": "Business Intelligence Analyst",
            "job_description": "Build Power BI and SQL reporting for operations.",
            "job_apply_link": "https://www.linkedin.com/jobs/view/abc123",
            "apply_options": [
                {"publisher": "Greenhouse", "apply_link": "https://boards.greenhouse.io/wirebelt/jobs/9", "is_direct": True},
            ],
            "job_is_remote": True,
            "job_city": "Londonderry", "job_state": "NH", "job_country": "US",
            "job_publisher": "LinkedIn",
        },
        {
            "job_id": "def456",
            "employer_name": "Acme Manufacturing",
            "job_title": "Data Analyst",
            "job_description": "ETL and dashboards in Tableau.",
            "job_apply_link": "https://acme.wd1.myworkdayjobs.com/careers/job/9",
            "apply_options": [],
            "job_is_remote": True,
            "job_country": "US",
        },
    ],
}

VOCAB = ["Power BI", "SQL", "Tableau", "ETL", "Python"]


def test_map_jsearch_jobs_normalizes_specs():
    specs = map_jsearch_jobs(_PAYLOAD, vocab=VOCAB)
    assert len(specs) == 2
    bi = specs[0]
    assert bi["platform"] == "greenhouse"            # detected ATS
    assert bi["external_id"] == "jsearch:abc123"
    assert bi["title"] == "Business Intelligence Analyst"
    assert bi["url"] == "https://boards.greenhouse.io/wirebelt/jobs/9"   # direct option chosen
    assert bi["submission_channel"] == "browser"
    assert bi["platform_meta"]["company"] == "Wire Belt Co"
    assert "Power BI" in bi["skills_required"] and "SQL" in bi["skills_required"]


def test_map_jsearch_jobs_external_channel_for_workday():
    specs = map_jsearch_jobs(_PAYLOAD, vocab=VOCAB)
    acme = specs[1]
    assert acme["platform"] == "external"
    assert acme["submission_channel"] == "external"
    assert acme["url"] == "https://acme.wd1.myworkdayjobs.com/careers/job/9"


def test_map_jsearch_jobs_skips_entries_without_id_or_title():
    payload = {"data": [{"employer_name": "X"}, {"job_id": "1", "job_title": ""}]}
    assert map_jsearch_jobs(payload, vocab=VOCAB) == []


def test_map_jsearch_jobs_notgreenhouse_is_external():
    """Regression: host suffix false positive — notgreenhouse.io must get platform='external'."""
    payload = {
        "data": [
            {
                "job_id": "ng1",
                "employer_name": "Not Greenhouse Inc",
                "job_title": "Software Engineer",
                "job_description": "Write code.",
                "job_apply_link": "https://notgreenhouse.io/jobs/1",
                "apply_options": [],
                "job_is_remote": False,
                "job_country": "US",
            }
        ]
    }
    specs = map_jsearch_jobs(payload, vocab=VOCAB)
    assert len(specs) == 1
    spec = specs[0]
    assert spec["platform"] == "external", (
        f"Expected 'external' but got '{spec['platform']}' — host-suffix false positive"
    )
    assert spec["submission_channel"] == "external"


def test_map_jsearch_jobs_persists_apply_options():
    specs = map_jsearch_jobs(_PAYLOAD, vocab=VOCAB)
    bi = specs[0]
    assert bi["platform_meta"]["apply_options"] == [
        {"publisher": "Greenhouse", "apply_link": "https://boards.greenhouse.io/wirebelt/jobs/9", "is_direct": True},
    ]
    # Workday job had no options -> stored as empty list, not dropped
    assert specs[1]["platform_meta"]["apply_options"] == []
