"""ORM tests for budget_settings and spend_events."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.db.models import Base, BudgetSettingsDB, SpendEventDB, SpendKind


@pytest.fixture()
async def session():
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def test_budget_settings_defaults(session: AsyncSession):
    row = BudgetSettingsDB(id=1)
    session.add(row)
    await session.commit()
    loaded = (await session.execute(select(BudgetSettingsDB))).scalar_one()
    assert loaded.connects_per_period == 60
    assert loaded.generation_apps_per_period == 20
    assert loaded.period == "week"


async def test_spend_event_persists(session: AsyncSession):
    e = SpendEventDB(kind=SpendKind.connects, amount=10.0, opportunity_id=None,
                     created_at=datetime(2026, 5, 22, tzinfo=UTC))
    session.add(e)
    await session.commit()
    loaded = (await session.execute(select(SpendEventDB))).scalar_one()
    assert loaded.kind == SpendKind.connects
    assert loaded.amount == 10.0
