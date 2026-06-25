"""Application history API endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.enums import ApplicationOutcome
from backend.db.database import get_session
from backend.db.models import ApplicationHistoryDB

router = APIRouter(prefix="/api/history", tags=["history"])


class HistoryCreateBody(BaseModel):
    """Body for POST /api/history — record a new application."""

    contract_id: int
    proposal_id: int
    connects_spent: Optional[int] = None
    outcome: ApplicationOutcome = ApplicationOutcome.submitted


class HistoryEntry(BaseModel):
    """Response model for a single history entry."""

    id: int
    contract_id: int
    proposal_id: int
    connects_spent: Optional[int] = None
    outcome: ApplicationOutcome
    submitted_at: Optional[datetime] = None
    outcome_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class HistoryStats(BaseModel):
    """Aggregated statistics for the history endpoint."""

    total_applications: int
    connects_spent: int
    response_rate: float
    outcomes_breakdown: dict[str, int]


@router.get("")
async def list_history(
    session: AsyncSession = Depends(get_session),
) -> list[HistoryEntry]:
    """List all application history entries, newest first."""
    result = await session.execute(
        select(ApplicationHistoryDB).order_by(
            ApplicationHistoryDB.submitted_at.desc()
        )
    )
    rows = result.scalars().all()
    return [HistoryEntry.model_validate(row) for row in rows]


@router.post("", status_code=201)
async def create_history(
    body: HistoryCreateBody,
    session: AsyncSession = Depends(get_session),
) -> HistoryEntry:
    """Create a new application history entry."""
    entry = ApplicationHistoryDB(
        contract_id=body.contract_id,
        proposal_id=body.proposal_id,
        connects_spent=body.connects_spent,
        outcome=body.outcome,
        submitted_at=datetime.now(UTC),
    )
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return HistoryEntry.model_validate(entry)


@router.get("/stats")
async def history_stats(
    session: AsyncSession = Depends(get_session),
) -> HistoryStats:
    """Return aggregated application statistics."""
    # Total applications
    total_result = await session.execute(
        select(func.count(ApplicationHistoryDB.id))
    )
    total_applications = total_result.scalar() or 0

    # Total connects spent
    connects_result = await session.execute(
        select(func.coalesce(func.sum(ApplicationHistoryDB.connects_spent), 0))
    )
    connects_spent = connects_result.scalar() or 0

    # Outcomes breakdown
    outcome_result = await session.execute(
        select(ApplicationHistoryDB.outcome, func.count(ApplicationHistoryDB.id)).group_by(
            ApplicationHistoryDB.outcome
        )
    )
    outcomes_breakdown: dict[str, int] = {}
    for outcome_val, count in outcome_result.all():
        key = outcome_val.value if hasattr(outcome_val, "value") else str(outcome_val)
        outcomes_breakdown[key] = count

    # Response rate: fraction of applications that got any response
    # (anything other than "submitted" or "no_response")
    responded = sum(
        count
        for outcome_str, count in outcomes_breakdown.items()
        if outcome_str not in ("submitted", "no_response")
    )
    response_rate = (responded / total_applications) if total_applications > 0 else 0.0

    return HistoryStats(
        total_applications=total_applications,
        connects_spent=connects_spent,
        response_rate=response_rate,
        outcomes_breakdown=outcomes_breakdown,
    )
