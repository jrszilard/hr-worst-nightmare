"""Shared test fixtures for the contract-finder test suite."""

import os

# Set dummy env vars BEFORE any application code is imported, so that
# pydantic-settings validation in backend.config doesn't fail.
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("PROFILE_DIR", "tests/fixtures/profile")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.db.models import Base


@pytest.fixture()
async def db_engine():
    """Create an in-memory async SQLite engine with all tables."""
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture()
async def db_session(db_engine):
    """Yield an async session bound to the in-memory engine."""
    session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
