import pytest
from sqlalchemy import select

from backend.core.board_scan import scan_job_boards
from backend.db.models import OpportunityDB


_GH_PAYLOAD = {"jobs": [{"id": 1, "title": "AI Engineer (Python)",
               "absolute_url": "https://boards.greenhouse.io/anthropic/jobs/1",
               "location": {"name": "Remote"}, "content": "Python and Claude API."}]}
_LEVER_PAYLOAD = [{"id": "x1", "text": "Data Engineer", "categories": {"location": "Remote"},
                   "applyUrl": "https://jobs.lever.co/example-co/x1/apply",
                   "descriptionPlain": "Python SQL Pandas."}]
_ASHBY_PAYLOAD = {"jobs": [{"id": "a1", "title": "Analytics Engineer",
                   "jobUrl": "https://jobs.ashbyhq.com/acme/a1",
                   "location": "Remote - United States", "workplaceType": "Remote",
                   "isRemote": True, "descriptionPlain": "SQL data visualization."}]}


@pytest.mark.asyncio
async def test_scan_ingests_from_all_board_types(db_session):
    config = {"greenhouse": ["anthropic"], "lever": ["example-co"], "ashby": ["acme"]}

    async def fake_fetch(vendor: str, slug: str):
        return {"greenhouse": _GH_PAYLOAD, "lever": _LEVER_PAYLOAD, "ashby": _ASHBY_PAYLOAD}[vendor]

    summary = await scan_job_boards(db_session, config=config, fetch=fake_fetch, threshold=0.0)
    await db_session.commit()
    rows = (await db_session.execute(select(OpportunityDB))).scalars().all()
    platforms = sorted({r.platform for r in rows})
    assert platforms == ["ashby", "greenhouse", "lever"]
    assert summary["total"] == 3


@pytest.mark.asyncio
async def test_one_board_failure_does_not_abort(db_session):
    config = {"greenhouse": ["anthropic"], "lever": ["broken"]}

    async def fake_fetch(vendor: str, slug: str):
        if vendor == "lever":
            raise RuntimeError("429 rate limited")
        return _GH_PAYLOAD

    summary = await scan_job_boards(db_session, config=config, fetch=fake_fetch, threshold=0.0)
    await db_session.commit()
    rows = (await db_session.execute(select(OpportunityDB))).scalars().all()
    assert {r.platform for r in rows} == {"greenhouse"}
    assert "lever:broken" in summary["errors"][0]


@pytest.mark.asyncio
async def test_criteria_filters_obvious_non_fit_roles_before_store(db_session):
    payload = {"jobs": [
        {"id": 1, "title": "Data Scientist", "absolute_url": "https://x/jobs/1",
         "location": {"name": "Remote"}, "content": "Python SQL analytics."},
        {"id": 2, "title": "Transaction Manager", "absolute_url": "https://x/jobs/2",
         "location": {"name": "Remote"}, "content": "Excel spreadsheets."},
    ]}
    config = {
        "greenhouse": ["company"],
        "criteria": {
            "title_include_any": ["data"],
            "text_include_any": ["python"],
            "exclude_title_any": ["transaction manager"],
        },
    }

    async def fake_fetch(vendor: str, slug: str):
        return payload

    summary = await scan_job_boards(db_session, config=config, fetch=fake_fetch, threshold=0.0)
    await db_session.commit()
    rows = (await db_session.execute(select(OpportunityDB))).scalars().all()
    assert [r.title for r in rows] == ["Data Scientist"]
    assert summary["total"] == 1
    assert summary["criteria_filtered"] == 1


@pytest.mark.asyncio
async def test_short_criteria_terms_match_words_not_substrings(db_session):
    payload = {"jobs": [
        {"id": 1, "title": "AI Data Scientist", "absolute_url": "https://x/jobs/1",
         "location": {"name": "Remote"}, "content": "Models."},
        {"id": 2, "title": "Paid Media Manager", "absolute_url": "https://x/jobs/2",
         "location": {"name": "Remote"}, "content": "Marketing."},
    ]}
    config = {"greenhouse": ["company"], "criteria": {"title_include_any": ["ai"]}}

    async def fake_fetch(vendor: str, slug: str):
        return payload

    summary = await scan_job_boards(db_session, config=config, fetch=fake_fetch, threshold=0.0)
    await db_session.commit()
    rows = (await db_session.execute(select(OpportunityDB))).scalars().all()
    assert [r.title for r in rows] == ["AI Data Scientist"]
    assert summary["criteria_filtered"] == 1


@pytest.mark.asyncio
async def test_us_only_location_filter_excludes_non_us_and_ambiguous_remote(db_session):
    payload = {"jobs": [
        {"id": 1, "title": "Data Scientist", "absolute_url": "https://x/jobs/1",
         "location": {"name": "Remote - United States"}, "content": "Python analytics."},
        {"id": 2, "title": "Data Engineer", "absolute_url": "https://x/jobs/2",
         "location": {"name": "San Francisco, CA"}, "content": "Data pipelines."},
        {"id": 3, "title": "Data Scientist", "absolute_url": "https://x/jobs/3",
         "location": {"name": "London, UK"}, "content": "Python analytics."},
        {"id": 4, "title": "Data Analyst", "absolute_url": "https://x/jobs/4",
         "location": {"name": "Remote"}, "content": "Analytics."},
        {"id": 5, "title": "Data Analyst", "absolute_url": "https://x/jobs/5",
         "location": {"name": "Dublin OR London"}, "content": "Analytics."},
    ]}
    config = {"greenhouse": ["company"], "criteria": {"us_only": True, "title_include_any": ["data"]}}

    async def fake_fetch(vendor: str, slug: str):
        return payload

    summary = await scan_job_boards(db_session, config=config, fetch=fake_fetch, threshold=0.0)
    await db_session.commit()
    rows = (await db_session.execute(select(OpportunityDB).order_by(OpportunityDB.external_id))).scalars().all()
    assert [r.title for r in rows] == ["Data Scientist", "Data Engineer"]
    assert [r.platform_meta["location"] for r in rows] == ["Remote - United States", "San Francisco, CA"]
    assert summary["criteria_filtered"] == 3


@pytest.mark.asyncio
async def test_generic_title_can_match_by_multiple_text_or_skill_signals(db_session):
    payload = {"jobs": [
        {"id": 1, "title": "Platform Consultant", "absolute_url": "https://x/jobs/1",
         "location": {"name": "Remote - United States"},
         "content": "Build LLM workflow automation for data visualization teams."},
        {"id": 2, "title": "Backend Engineer", "absolute_url": "https://x/jobs/2",
         "location": {"name": "Remote - United States"},
         "content": "Python SQL Pandas internal tooling."},
        {"id": 3, "title": "Backend Engineer", "absolute_url": "https://x/jobs/3",
         "location": {"name": "Remote - United States"},
         "content": "Python services."},
    ]}
    config = {
        "greenhouse": ["company"],
        "criteria": {
            "us_only": True,
            "title_include_any": ["data scientist"],
            "text_include_min": 2,
            "text_include_any": ["llm", "workflow automation", "data visualization"],
            "skills_include_min": 2,
            "skills_include_any": ["Python", "SQL", "Pandas"],
        },
    }

    async def fake_fetch(vendor: str, slug: str):
        return payload

    summary = await scan_job_boards(db_session, config=config, fetch=fake_fetch, threshold=0.0)
    await db_session.commit()
    rows = (await db_session.execute(select(OpportunityDB).order_by(OpportunityDB.external_id))).scalars().all()
    assert [r.title for r in rows] == ["Platform Consultant", "Backend Engineer"]
    assert summary["criteria_filtered"] == 1
