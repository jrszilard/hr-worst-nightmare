from backend.core.enums import SubmissionChannel


def test_auto_channel_exists():
    assert SubmissionChannel.auto.value == "auto"


from backend.platforms.greenhouse.board_client import map_greenhouse_jobs

VOCAB = ["Python", "SQL", "Claude API"]

_PAYLOAD = {
    "jobs": [
        {
            "id": 4567,
            "title": "Senior Data Engineer",
            "absolute_url": "https://boards.greenhouse.io/acme/jobs/4567",
            "location": {"name": "Remote - US"},
            "content": "We use &lt;b&gt;Python&lt;/b&gt; and SQL heavily.",
            "updated_at": "2026-05-20T12:00:00-04:00",
        }
    ]
}


def test_maps_greenhouse_payload():
    specs = map_greenhouse_jobs("acme", _PAYLOAD, vocab=VOCAB)
    assert len(specs) == 1
    s = specs[0]
    assert s["platform"] == "greenhouse"
    assert s["external_id"] == "acme:4567"
    assert s["title"] == "Senior Data Engineer"
    assert s["url"] == "https://boards.greenhouse.io/acme/jobs/4567"
    assert s["submission_channel"] == "browser"
    assert s["platform_meta"]["company"] == "acme"
    assert s["platform_meta"]["ats_vendor"] == "greenhouse"
    assert s["platform_meta"]["location"] == "Remote - US"
    # HTML entities decoded + tags stripped for description, skills extracted
    assert "Python" in s["description"] and "<b>" not in s["description"]
    assert s["skills_required"] == ["Python", "SQL"]


def test_empty_jobs_list():
    assert map_greenhouse_jobs("acme", {"jobs": []}, vocab=VOCAB) == []


def test_careers_portal_absolute_url_rewritten_to_fillable_greenhouse_form():
    # Some companies configure a careers-portal absolute_url (e.g. Pinterest). It is NOT
    # engine-fillable, so the assisted apply 400s and discovery reads 0 questions. The board
    # token + id are known, so map to the canonical Greenhouse form and keep the portal link.
    from backend.platforms.ats_registry import is_engine_fillable
    payload = {"jobs": [{
        "id": 7481476,
        "title": "Sr. Data Analyst",
        "absolute_url": "https://www.pinterestcareers.com/jobs/?gh_jid=7481476",
        "location": {"name": "Remote - US"},
        "content": "Python and SQL.",
    }]}
    s = map_greenhouse_jobs("pinterest", payload, vocab=VOCAB)[0]
    assert s["url"] == "https://job-boards.greenhouse.io/pinterest/jobs/7481476"
    assert is_engine_fillable(s["url"])
    assert s["platform_meta"]["posting_url"] == "https://www.pinterestcareers.com/jobs/?gh_jid=7481476"


def test_native_greenhouse_absolute_url_is_kept():
    # When the configured URL is already an engine-fillable Greenhouse form, keep it as-is.
    s = map_greenhouse_jobs("acme", _PAYLOAD, vocab=VOCAB)[0]
    assert s["url"] == "https://boards.greenhouse.io/acme/jobs/4567"
    assert s["platform_meta"]["posting_url"] == "https://boards.greenhouse.io/acme/jobs/4567"


def test_jobs_missing_an_id_are_skipped_not_crashed():
    # A job needs a stable id for both external_id and the canonical fillable URL. Greenhouse
    # always sends one, but a malformed/partial payload must not KeyError the whole batch
    # (PR #14 follow-up). Skip the id-less job and map the rest — and the surviving job's
    # external_id AND url must still be built from the id (both lines use job_id).
    payload = {"jobs": [
        {"title": "Orphan, no id", "location": {"name": "Remote - US"}, "content": "Python"},
        {"id": 99, "title": "Has id",
         "absolute_url": "https://www.pinterestcareers.com/jobs/?gh_jid=99",  # not fillable
         "location": {"name": "Remote - US"}, "content": "SQL"},
    ]}
    specs = map_greenhouse_jobs("acme", payload, vocab=VOCAB)
    assert len(specs) == 1
    assert specs[0]["external_id"] == "acme:99"
    assert specs[0]["url"] == "https://job-boards.greenhouse.io/acme/jobs/99"
