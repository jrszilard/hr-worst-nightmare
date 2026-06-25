import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.core.enums import OpportunityKind, SubmissionChannel
from backend.db.models import Base, OpportunityDB


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
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_jobs_list_includes_channel(client, session_factory):
    async with session_factory() as s:
        s.add(OpportunityDB(platform="greenhouse", external_id="c1", title="T",
                            kind=OpportunityKind.job, match_score=0.5,
                            submission_channel=SubmissionChannel.auto,
                            platform_meta={"location": "Remote - United States"}))
        await s.commit()
    resp = await client.get("/api/jobs")
    assert resp.status_code == 200
    assert resp.json()[0]["submission_channel"] == "auto"
