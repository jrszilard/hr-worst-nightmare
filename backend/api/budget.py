"""Budget settings + usage API."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.budget_store import display_dollars, get_settings, period_usage
from backend.core.budget import week_start
from backend.core.enums import BudgetPeriod
from backend.db.database import get_session

router = APIRouter(prefix="/api/budget", tags=["budget"])


class BudgetConfig(BaseModel):
    connects_per_period: int
    generation_apps_per_period: int
    generation_dollars_per_period: float
    period: BudgetPeriod
    per_run_max_apps: int | None

    model_config = {"from_attributes": True}


class BudgetUsage(BaseModel):
    connects: float
    generation_apps: float
    generation_dollars: float


class BudgetStatus(BaseModel):
    config: BudgetConfig
    used: BudgetUsage
    remaining: BudgetUsage
    period_start: datetime


async def _status(session: AsyncSession) -> BudgetStatus:
    settings = await get_settings(session)
    now = datetime.now(UTC)
    connects_used, gen_used, dollars_used = await period_usage(session, now)
    config = BudgetConfig.model_validate(settings)
    shown_dollars = display_dollars(dollars_used, gen_used)
    used = BudgetUsage(connects=connects_used, generation_apps=gen_used,
                       generation_dollars=shown_dollars)
    remaining = BudgetUsage(
        connects=max(0.0, config.connects_per_period - connects_used),
        generation_apps=max(0.0, config.generation_apps_per_period - gen_used),
        generation_dollars=max(0.0, config.generation_dollars_per_period - shown_dollars),
    )
    return BudgetStatus(config=config, used=used, remaining=remaining,
                        period_start=week_start(now))


@router.get("")
async def get_budget(session: AsyncSession = Depends(get_session)) -> BudgetStatus:
    return await _status(session)


@router.put("")
async def update_budget(body: BudgetConfig,
                        session: AsyncSession = Depends(get_session)) -> BudgetStatus:
    settings = await get_settings(session)
    settings.connects_per_period = body.connects_per_period
    settings.generation_apps_per_period = body.generation_apps_per_period
    settings.generation_dollars_per_period = body.generation_dollars_per_period
    settings.period = body.period
    settings.per_run_max_apps = body.per_run_max_apps
    await session.commit()
    return await _status(session)
