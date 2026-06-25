"""Availability settings API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.availability import get_availability as _get_availability
from backend.core.availability import update_availability as _update_availability
from backend.core.models import AvailabilityConfig
from backend.db.database import get_session

router = APIRouter(prefix="/api/availability", tags=["availability"])


@router.get("")
async def get_availability(
    session: AsyncSession = Depends(get_session),
) -> AvailabilityConfig:
    """Return the current availability settings."""
    return await _get_availability(session)


@router.put("")
async def update_availability(
    body: AvailabilityConfig,
    session: AsyncSession = Depends(get_session),
) -> AvailabilityConfig:
    """Update availability settings and return the new state."""
    return await _update_availability(session, body)
