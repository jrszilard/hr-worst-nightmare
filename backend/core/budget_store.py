"""DB helpers for budget settings (singleton) + period usage aggregation."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.budget import EST_DOLLARS_PER_APP, week_start
from backend.db.models import BudgetSettingsDB, SpendEventDB, SpendKind

_SETTINGS_ROW_ID = 1


async def get_settings(session: AsyncSession) -> BudgetSettingsDB:
    row = (
        await session.execute(
            select(BudgetSettingsDB).where(BudgetSettingsDB.id == _SETTINGS_ROW_ID)
        )
    ).scalar_one_or_none()
    if row is None:
        row = BudgetSettingsDB(id=_SETTINGS_ROW_ID)
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return row


async def period_usage(session: AsyncSession, now: datetime) -> tuple[float, float, float]:
    """Return (connects_used, generation_apps_used, generation_dollars_used) this period."""
    start = week_start(now)
    rows = (
        await session.execute(
            select(SpendEventDB).where(SpendEventDB.created_at >= start)
        )
    ).scalars().all()
    connects = sum(r.amount for r in rows if r.kind == SpendKind.connects)
    gen_apps = sum(r.amount for r in rows if r.kind == SpendKind.generation)
    dollars = sum(r.amount for r in rows if r.kind == SpendKind.generation_dollars)
    return connects, gen_apps, dollars


def est_dollars(gen_apps: float) -> float:
    return round(gen_apps * EST_DOLLARS_PER_APP, 2)


def display_dollars(actual_dollars: float, gen_apps: float) -> float:
    """Real spend if any dollar events exist, else the per-app estimate (legacy rows)."""
    return round(actual_dollars, 2) if actual_dollars > 0 else est_dollars(gen_apps)
