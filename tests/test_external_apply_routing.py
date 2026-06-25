import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from backend.core.platform import SubmitResult
from backend.db.models import Base, OpportunityDB, OpportunityKind, ContractStatus, JobApplicationDB


@pytest.fixture()
async def api_engine():
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture()
async def session_factory(api_engine):
    return async_sessionmaker(api_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture()
async def client(session_factory):
    from backend.db.database import get_session
    from backend.main import app

    async def _override():
        async with session_factory() as s:
            yield s
    app.dependency_overrides[get_session] = _override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def test_external_apply_rejects_example_com(client, session_factory, monkeypatch):
    """Regression: external channel with example.com URL must return 400, not open a browser."""
    from backend.core.enums import SubmissionChannel
    async with session_factory() as s:
        j = OpportunityDB(
            platform="external", external_id="jsearch:example1", title="Data Analyst",
            kind=OpportunityKind.job, match_score=0.9, description_fit=0.9,
            status=ContractStatus.reviewed, is_finalist=True,
            url="https://example.com/jobs/x",
            submission_channel=SubmissionChannel.external,
            platform_meta={"company": "Example Corp"},
        )
        s.add(j); await s.flush()
        s.add(JobApplicationDB(opportunity_id=j.id, cover_letter="Hi, Pat here.",
                              review_flags=[], applied=False))
        await s.commit(); jid = j.id

    # Should raise 400, not attempt to open the browser
    r = await client.post(f"/api/jobs/{jid}/apply")
    assert r.status_code == 400, r.text
    assert "valid posting URL" in r.json()["detail"]


async def test_external_apply_generates_and_opens_posting(client, session_factory, monkeypatch):
    import backend.api.jobs as jobs
    from backend.core.enums import SubmissionChannel
    async with session_factory() as s:
        j = OpportunityDB(
            platform="external", external_id="jsearch:x1", title="Data Analyst",
            kind=OpportunityKind.job, match_score=0.9, description_fit=0.9,
            status=ContractStatus.reviewed, is_finalist=True,
            url="https://acme.wd1.myworkdayjobs.com/job/1",
            submission_channel=SubmissionChannel.external,
            platform_meta={"company": "Acme"},
        )
        s.add(j); await s.flush()
        s.add(JobApplicationDB(opportunity_id=j.id, cover_letter="Hi, Pat here.",
                              review_flags=[], applied=False))
        await s.commit(); jid = j.id

    opened = {}
    async def fake_open(*, url, headless=False):
        opened["url"] = url
        return SubmitResult(filled=False, submitted=False, detail="opened posting for manual apply")
    monkeypatch.setattr(jobs, "open_posting_for_review", fake_open)

    r = await client.post(f"/api/jobs/{jid}/apply")
    assert r.status_code == 200, r.text
    assert opened["url"] == "https://acme.wd1.myworkdayjobs.com/job/1"
    assert r.json()["filled"] is False
    assert "manual apply" in r.json()["detail"]
