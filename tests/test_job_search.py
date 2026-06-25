# tests/test_job_search.py
import pytest
from sqlalchemy import select
from backend.core.job_search import search_jobs
from backend.db.models import OpportunityDB, OpportunityKind


@pytest.fixture()
def fake_payload():
    return {"data": [
        {"job_id": "1", "employer_name": "Wire Belt Co", "job_title": "Data Analyst",
         "job_description": "SQL and Power BI reporting.",
         "job_apply_link": "https://boards.greenhouse.io/wb/jobs/1",
         "apply_options": [], "job_is_remote": True, "job_country": "US"},
        {"job_id": "2", "employer_name": "Acme Mfg", "job_title": "BI Engineer",
         "job_description": "Tableau dashboards, ETL.",
         "job_apply_link": "https://acme.wd1.myworkdayjobs.com/job/2",
         "apply_options": [], "job_is_remote": True, "job_country": "US"},
    ]}


async def test_search_jobs_ingests_and_screens(db_session, fake_payload):
    async def fake_fetch(query, **kw):
        return fake_payload  # same payload regardless of query

    config = {"queries": ["Data Analyst"], "location": "United States",
              "remote_only": True, "pages_per_query": 1}
    summary = await search_jobs(db_session, config=config, fetch=fake_fetch, threshold=0.0)
    await db_session.commit()

    assert summary["total"] == 2
    rows = (await db_session.execute(
        select(OpportunityDB).where(OpportunityDB.kind == OpportunityKind.job)
    )).scalars().all()
    channels = {r.platform: r.submission_channel.value for r in rows}
    assert channels["greenhouse"] == "browser"
    assert channels["external"] == "external"


async def test_search_jobs_dedupes_same_job_across_queries(db_session, fake_payload):
    async def fake_fetch(query, **kw):
        return fake_payload

    config = {"queries": ["Data Analyst", "BI Engineer"], "location": "US",
              "remote_only": True, "pages_per_query": 1}
    summary = await search_jobs(db_session, config=config, fetch=fake_fetch, threshold=0.0)
    await db_session.commit()
    # 2 queries x 2 jobs = 4 specs, but upsert by (platform, external_id) -> 2 rows.
    rows = (await db_session.execute(select(OpportunityDB))).scalars().all()
    assert len([r for r in rows if r.kind == OpportunityKind.job]) == 2
