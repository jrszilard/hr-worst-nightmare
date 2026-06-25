"""Tests for the budget API."""

from datetime import UTC, datetime

import pytest
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


async def test_get_budget_returns_defaults_and_zero_usage(client: AsyncClient):
    body = (await client.get("/api/budget")).json()
    assert body["config"]["connects_per_period"] == 60
    assert body["used"]["connects"] == 0
    assert body["remaining"]["connects"] == 60


async def test_put_budget_updates_config(client: AsyncClient):
    new = {"connects_per_period": 30, "generation_apps_per_period": 10,
           "generation_dollars_per_period": 3.0, "period": "week", "per_run_max_apps": 3}
    body = (await client.put("/api/budget", json=new)).json()
    assert body["config"]["connects_per_period"] == 30
    assert body["remaining"]["connects"] == 30


async def test_usage_counts_current_period_spend(client: AsyncClient, session_factory):
    async with session_factory() as s:
        s.add(SpendEventDB(kind=SpendKind.connects, amount=25.0,
                           created_at=datetime.now(UTC)))
        await s.commit()
    body = (await client.get("/api/budget")).json()
    assert body["used"]["connects"] == 25
    assert body["remaining"]["connects"] == 35
