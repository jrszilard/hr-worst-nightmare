"""Tests for PreferenceStore load/save round-trips."""

import pytest

from backend.core.preference_store import PreferenceStore


@pytest.mark.asyncio
async def test_load_empty_returns_empty_dict(db_session):
    assert await PreferenceStore.load_weights(db_session) == {}


@pytest.mark.asyncio
async def test_save_then_load_round_trips(db_session):
    await PreferenceStore.save_weights(db_session, {"sql": 0.5, "sales": -0.25})
    assert await PreferenceStore.load_weights(db_session) == {"sql": 0.5, "sales": -0.25}


@pytest.mark.asyncio
async def test_save_upserts_existing_and_drops_zeroed(db_session):
    await PreferenceStore.save_weights(db_session, {"sql": 0.5})
    await PreferenceStore.save_weights(db_session, {"sql": 0.75, "python": 0.25})
    weights = await PreferenceStore.load_weights(db_session)
    assert weights == {"sql": 0.75, "python": 0.25}
