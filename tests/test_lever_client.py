from backend.platforms.lever.board_client import map_lever_jobs

VOCAB = ["Python", "SQL", "Pandas"]

_PAYLOAD = [
    {
        "id": "abc-123",
        "text": "Machine Learning Engineer",
        "categories": {"team": "ML", "location": "Remote", "commitment": "Full-time"},
        "hostedUrl": "https://jobs.lever.co/acme/abc-123",
        "applyUrl": "https://jobs.lever.co/acme/abc-123/apply",
        "descriptionPlain": "Build pipelines in Python and Pandas.",
    }
]


def test_maps_lever_payload():
    specs = map_lever_jobs("acme", _PAYLOAD, vocab=VOCAB)
    assert len(specs) == 1
    s = specs[0]
    assert s["platform"] == "lever"
    assert s["external_id"] == "acme:abc-123"
    assert s["title"] == "Machine Learning Engineer"
    # prefer the apply URL so submission lands on the form page
    assert s["url"] == "https://jobs.lever.co/acme/abc-123/apply"
    assert s["submission_channel"] == "browser"
    assert s["platform_meta"]["location"] == "Remote"
    assert s["skills_required"] == ["Python", "Pandas"]


def test_empty_list():
    assert map_lever_jobs("acme", [], vocab=VOCAB) == []


def test_jobs_missing_an_id_are_skipped_not_crashed():
    # A job with no id can't form a stable external_id; a malformed/partial payload must
    # not KeyError the whole batch (parity with the Greenhouse mapper hardening).
    payload = [
        {"text": "Orphan, no id", "categories": {"location": "Remote"},
         "descriptionPlain": "Python"},
        {"id": "abc-123", "text": "Has id",
         "hostedUrl": "https://jobs.lever.co/acme/abc-123",
         "categories": {"location": "Remote"}, "descriptionPlain": "SQL"},
    ]
    specs = map_lever_jobs("acme", payload, vocab=VOCAB)
    assert [s["external_id"] for s in specs] == ["acme:abc-123"]
