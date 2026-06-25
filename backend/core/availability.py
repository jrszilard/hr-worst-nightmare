"""CRUD helpers for the single-row availability settings table.

Provides ``get_availability`` and ``update_availability`` as FastAPI
dependency-compatible async functions.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.models import AvailabilityConfig
from backend.db.models import AvailabilitySettingsDB

# The single-row PK.
_SETTINGS_ROW_ID = 1


async def get_availability(session: AsyncSession) -> AvailabilityConfig:
    """Return the current availability settings, creating defaults if absent.

    This is also usable as a FastAPI dependency when combined with
    ``Depends(get_session)``.
    """
    result = await session.execute(
        select(AvailabilitySettingsDB).where(
            AvailabilitySettingsDB.id == _SETTINGS_ROW_ID
        )
    )
    row = result.scalar_one_or_none()

    if row is None:
        # First call — insert defaults.
        row = AvailabilitySettingsDB(id=_SETTINGS_ROW_ID)
        session.add(row)
        await session.commit()
        await session.refresh(row)

    return AvailabilityConfig.model_validate(row, from_attributes=True)


async def update_availability(
    session: AsyncSession,
    updates: AvailabilityConfig,
) -> AvailabilityConfig:
    """Persist updated availability settings and return the new state.

    All fields from *updates* overwrite the stored values.
    """
    result = await session.execute(
        select(AvailabilitySettingsDB).where(
            AvailabilitySettingsDB.id == _SETTINGS_ROW_ID
        )
    )
    row = result.scalar_one_or_none()

    if row is None:
        row = AvailabilitySettingsDB(id=_SETTINGS_ROW_ID)
        session.add(row)

    # Apply every field from the Pydantic model.
    row.hours_per_week = updates.hours_per_week
    row.max_concurrent_contracts = updates.max_concurrent_contracts
    row.current_committed_hours = updates.current_committed_hours
    row.preferred_duration = updates.preferred_duration
    row.preferred_contract_type = updates.preferred_contract_type
    row.min_hourly_rate = updates.min_hourly_rate
    row.min_fixed_budget = updates.min_fixed_budget
    row.hourly_value = updates.hourly_value

    await session.commit()
    await session.refresh(row)

    return AvailabilityConfig.model_validate(row, from_attributes=True)
