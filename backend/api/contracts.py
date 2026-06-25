"""Contract listing, detail, and ingestion API endpoints."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.enums import ContractStatus, ContractType
from backend.core.matching import calculate_match_score
from backend.core.models import AvailabilityConfig, Contract, ContractCreate
from backend.core.scoring import assign_indicator, calculate_roi_score
from backend.db.database import get_session
from backend.db.models import ContractDB
from backend.portfolio.profile_loader import load_profile

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/contracts", tags=["contracts"])


def _contract_response(contract: Contract, all_roi_scores: list[float]) -> dict:
    """Build a contract response dict with the percentile indicator."""
    data = contract.model_dump()
    data["indicator"] = assign_indicator(contract.roi_score or 0.0, all_roi_scores)
    return data


@router.get("")
async def list_contracts(
    status: Optional[ContractStatus] = Query(None),
    min_roi: Optional[float] = Query(None),
    contract_type: Optional[ContractType] = Query(None),
    skill: Optional[str] = Query(None),
    budget_min: Optional[float] = Query(None),
    budget_max: Optional[float] = Query(None),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """Return contracts sorted by ROI score with indicator colours.

    Supports optional query-param filters: status, min_roi, contract_type,
    skill, budget_min, budget_max.
    """
    query = select(ContractDB)

    if status is not None:
        query = query.where(ContractDB.status == status)
    if contract_type is not None:
        query = query.where(ContractDB.contract_type == contract_type)
    if budget_min is not None:
        query = query.where(ContractDB.budget_min >= budget_min)
    if budget_max is not None:
        query = query.where(ContractDB.budget_max <= budget_max)

    result = await session.execute(query)
    rows = result.scalars().all()

    contracts = [Contract.model_validate(row) for row in rows]

    # Apply min_roi filter (post-query since roi_score may be None)
    if min_roi is not None:
        contracts = [c for c in contracts if (c.roi_score or 0.0) >= min_roi]

    # Apply skill filter (post-query — substring match against skills_required names)
    if skill is not None:
        skill_lower = skill.lower()
        contracts = [
            c
            for c in contracts
            if c.skills_required
            and any(skill_lower in s.lower() for s in c.skills_required)
        ]

    # Sort by ROI score descending (nulls last)
    contracts.sort(key=lambda c: c.roi_score or 0.0, reverse=True)

    # Collect all ROI scores for percentile calculation
    all_roi_scores = [c.roi_score for c in contracts if c.roi_score is not None]

    return [_contract_response(c, all_roi_scores) for c in contracts]


@router.get("/{contract_id}")
async def get_contract(
    contract_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Return a single contract with full details and indicator."""
    result = await session.execute(
        select(ContractDB).where(ContractDB.id == contract_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Contract not found")

    contract = Contract.model_validate(row)

    # Need all scores for indicator calculation
    all_result = await session.execute(
        select(ContractDB.roi_score).where(ContractDB.roi_score.isnot(None))
    )
    all_roi_scores = [r[0] for r in all_result.all()]

    return _contract_response(contract, all_roi_scores)


@router.post("")
async def create_contract(
    payload: ContractCreate,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Ingest a contract from an external scan or manual entry.

    Calculates match score and ROI score, then upserts into the DB.
    If a contract with the same platform + external_id exists, skip it.
    """
    # Check for duplicate
    existing = await session.execute(
        select(ContractDB).where(
            ContractDB.platform == payload.platform,
            ContractDB.external_id == payload.external_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Contract already exists")

    # Calculate match score
    profile = load_profile()
    skills = payload.skills_required or []
    match_result = calculate_match_score(skills, profile) if skills else None
    match_score = match_result.match_score if match_result else 0.0

    # Calculate ROI score
    contract_for_scoring = Contract(
        id=0, platform=payload.platform, external_id=payload.external_id,
        title=payload.title, description=payload.description,
        budget_min=payload.budget_min, budget_max=payload.budget_max,
        contract_type=payload.contract_type.value if payload.contract_type else "fixed",
        client_hire_rate=payload.client_hire_rate or 0.5,
        proposals_count=payload.proposals_count or 20,
        connects_cost=payload.connects_cost or 16,
        client_total_spent=payload.client_total_spent,
    )
    scoring = calculate_roi_score(match_score, contract_for_scoring, AvailabilityConfig())

    # Insert
    row = ContractDB(
        platform=payload.platform,
        external_id=payload.external_id,
        url=payload.url,
        title=payload.title,
        description=payload.description,
        skills_required=skills if skills else None,
        budget_min=payload.budget_min,
        budget_max=payload.budget_max,
        contract_type=ContractType(payload.contract_type) if payload.contract_type else None,
        duration=payload.duration,
        proposals_count=payload.proposals_count,
        client_hire_rate=payload.client_hire_rate,
        client_total_spent=payload.client_total_spent,
        client_location=payload.client_location,
        match_score=match_score,
        roi_score=scoring.roi_score,
        connects_cost=payload.connects_cost,
        client_questions=payload.client_questions if payload.client_questions else None,
        status=ContractStatus.new,
        posted_at=payload.posted_at or datetime.now(UTC),
        fetched_at=datetime.now(UTC),
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)

    contract = Contract.model_validate(row)
    all_result = await session.execute(
        select(ContractDB.roi_score).where(ContractDB.roi_score.isnot(None))
    )
    all_roi_scores = [r[0] for r in all_result.all()]

    logger.info("Ingested contract %s (match=%.0f%%, roi=%.1f)", payload.external_id, match_score * 100, scoring.roi_score)
    return _contract_response(contract, all_roi_scores)
