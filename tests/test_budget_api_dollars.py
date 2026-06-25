import pytest
from datetime import UTC, datetime
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.db.models import Base, SpendEventDB, SpendKind


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
async def test_budget_meter_reports_actual_dollars(client, session_factory):
    now = datetime.now(UTC)
    async with session_factory() as s:
        s.add(SpendEventDB(kind=SpendKind.generation, amount=2.0, created_at=now))
        s.add(SpendEventDB(kind=SpendKind.generation_dollars, amount=0.42, created_at=now))
        await s.commit()

    resp = await client.get("/api/budget")
    assert resp.status_code == 200
    used = resp.json()["used"]
    assert round(used["generation_dollars"], 2) == 0.42  # actual, not 2 * 0.05
