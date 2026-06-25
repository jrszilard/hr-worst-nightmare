"""Read-only view of learned skill-preference weights."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.preference_store import PreferenceStore
from backend.db.database import get_session

router = APIRouter(prefix="/api/preferences", tags=["preferences"])


class WeightOut(BaseModel):
    skill: str
    weight: float


class PreferencesOut(BaseModel):
    weights: list[WeightOut]


@router.get("")
async def get_preferences(
    session: AsyncSession = Depends(get_session),
) -> PreferencesOut:
    weights = await PreferenceStore.load_weights(session)
    items = [WeightOut(skill=k, weight=v) for k, v in weights.items()]
    items.sort(key=lambda w: w.weight, reverse=True)
    return PreferencesOut(weights=items)
