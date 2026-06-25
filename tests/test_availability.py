"""Tests for availability CRUD (backend.core.availability)."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.core.availability import get_availability, update_availability
from backend.core.enums import PreferredContractType, PreferredDuration
from backend.core.models import AvailabilityConfig


# ── get_availability ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_returns_defaults_when_empty(db_session):
    """First call should auto-create a row with sensible defaults."""
    config = await get_availability(db_session)
    assert isinstance(config, AvailabilityConfig)
    assert config.hours_per_week == 40
    assert config.max_concurrent_contracts == 3
    assert config.current_committed_hours == 0
    assert config.preferred_duration == PreferredDuration.any
    assert config.preferred_contract_type == PreferredContractType.both
    assert config.min_hourly_rate == 75.0
    assert config.min_fixed_budget == 500.0
    assert config.hourly_value == 100.0


@pytest.mark.asyncio
async def test_get_is_idempotent(db_session):
    """Calling get twice returns the same data and does not duplicate rows."""
    first = await get_availability(db_session)
    second = await get_availability(db_session)
    assert first == second


# ── update_availability ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_persists(db_session):
    """update_availability stores new values and they are returned by get."""
    new_config = AvailabilityConfig(
        hours_per_week=20,
        max_concurrent_contracts=2,
        current_committed_hours=10,
        preferred_duration=PreferredDuration.medium,
        preferred_contract_type=PreferredContractType.hourly,
        min_hourly_rate=100.0,
        min_fixed_budget=1000.0,
        hourly_value=125.0,
    )
    result = await update_availability(db_session, new_config)
    assert result.hours_per_week == 20
    assert result.min_hourly_rate == 100.0
    assert result.preferred_duration == PreferredDuration.medium

    # Verify via get
    fetched = await get_availability(db_session)
    assert fetched == new_config


@pytest.mark.asyncio
async def test_update_without_prior_get(db_session):
    """update works even if no row exists yet (cold start)."""
    config = AvailabilityConfig(
        hours_per_week=30,
        max_concurrent_contracts=5,
        current_committed_hours=5,
        preferred_duration=PreferredDuration.long,
        preferred_contract_type=PreferredContractType.fixed,
        min_hourly_rate=80.0,
        min_fixed_budget=750.0,
        hourly_value=110.0,
    )
    result = await update_availability(db_session, config)
    assert result.hours_per_week == 30
    assert result.preferred_contract_type == PreferredContractType.fixed


@pytest.mark.asyncio
async def test_multiple_updates(db_session):
    """Successive updates overwrite correctly."""
    first = AvailabilityConfig(hours_per_week=10)
    await update_availability(db_session, first)

    second = AvailabilityConfig(hours_per_week=50, min_hourly_rate=200.0)
    result = await update_availability(db_session, second)
    assert result.hours_per_week == 50
    assert result.min_hourly_rate == 200.0

    fetched = await get_availability(db_session)
    assert fetched.hours_per_week == 50


# ── Persistence across sessions (simulated) ─────────────────────────────────


@pytest.mark.asyncio
async def test_persists_across_sessions(db_engine):
    """Data written in one session is visible in a new session."""
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    # Session 1: write
    async with factory() as s1:
        await update_availability(
            s1,
            AvailabilityConfig(hours_per_week=15, min_hourly_rate=90.0),
        )

    # Session 2: read
    async with factory() as s2:
        config = await get_availability(s2)
        assert config.hours_per_week == 15
        assert config.min_hourly_rate == 90.0
