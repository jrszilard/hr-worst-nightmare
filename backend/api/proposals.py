"""Proposal generation, retrieval, update, and form-fill API endpoints."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.ai.contract_analyzer import analyze_contract
from backend.ai.proposal_generator import generate_proposal
from backend.core.availability import get_availability
from backend.core.enums import ContractStatus
from backend.core.matching import calculate_match_score
from backend.core.models import Contract, LoadedProfile, Proposal
from backend.db.database import get_session
from backend.db.models import ContractDB, ProposalDB
from backend.portfolio.profile_loader import get_profile

router = APIRouter(tags=["proposals"])


class ProposalUpdateBody(BaseModel):
    """Body for PUT /api/proposals/{id} — inline editing."""

    content: Optional[str] = None
    sections: Optional[list[dict]] = None
    bid_amount: Optional[float] = None
    estimated_duration: Optional[str] = None


@router.post("/api/contracts/{contract_id}/propose")
async def create_proposal(
    contract_id: int,
    session: AsyncSession = Depends(get_session),
    profile: LoadedProfile = Depends(get_profile),
) -> dict:
    """Analyse a contract, generate a proposal, and save it.

    Orchestration: get contract -> analyse -> match
    -> generate proposal -> save to DB -> return.
    """
    # 1. Load the contract
    result = await session.execute(
        select(ContractDB).where(ContractDB.id == contract_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Contract not found")

    contract = Contract.model_validate(row)

    # 2. Analyse the contract (AI)
    analysis = await analyze_contract(
        title=contract.title or "",
        description=contract.description or "",
        skills_tags=contract.skills_required or [],
        core_skills=[s.name for s in profile.core_skills],
        adjacent_skills=[s.name for s in profile.adjacent_skills],
    )

    # 3. Calculate match score
    match_result = calculate_match_score(
        analysis.extracted_skills, profile
    )

    # 4. Get availability
    availability = await get_availability(session)

    # 5. Generate proposal (AI)
    generated = await generate_proposal(
        contract=contract,
        profile=profile,
        availability=availability,
    )

    # 6. Determine version number
    version_result = await session.execute(
        select(ProposalDB.version)
        .where(ProposalDB.contract_id == contract_id)
        .order_by(ProposalDB.version.desc())
        .limit(1)
    )
    last_version = version_result.scalar_one_or_none()
    new_version = (last_version or 0) + 1

    # 7. Build full content from sections
    full_content = "\n\n".join(s.content for s in generated.sections)

    # 8. Save to DB
    proposal_db = ProposalDB(
        contract_id=contract_id,
        version=new_version,
        content=full_content,
        sections=[s.model_dump() for s in generated.sections],
        matched_case_studies=[
            sid
            for s in generated.sections
            for sid in (s.case_study_ids or [])
        ],
        bid_amount=generated.bid_amount,
        estimated_duration=generated.estimated_duration,
    )
    session.add(proposal_db)

    # Persist the computed match score and update contract status
    row.match_score = match_result.match_score
    row.status = ContractStatus.drafting

    await session.commit()
    await session.refresh(proposal_db)

    return Proposal.model_validate(proposal_db).model_dump()


@router.get("/api/proposals/{proposal_id}")
async def get_proposal(
    proposal_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Return a proposal with sections."""
    result = await session.execute(
        select(ProposalDB).where(ProposalDB.id == proposal_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Proposal not found")

    return Proposal.model_validate(row).model_dump()


@router.put("/api/proposals/{proposal_id}")
async def update_proposal(
    proposal_id: int,
    body: ProposalUpdateBody,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Update proposal content (for inline editing)."""
    result = await session.execute(
        select(ProposalDB).where(ProposalDB.id == proposal_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Proposal not found")

    if body.content is not None:
        row.content = body.content
    if body.sections is not None:
        row.sections = body.sections
    if body.bid_amount is not None:
        row.bid_amount = body.bid_amount
    if body.estimated_duration is not None:
        row.estimated_duration = body.estimated_duration

    await session.commit()
    await session.refresh(row)

    return Proposal.model_validate(row).model_dump()


@router.post("/api/proposals/{proposal_id}/fill")
async def fill_proposal(
    proposal_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Trigger Chrome form filling for a proposal.

    Requires the user to be on the Upwork proposal page.
    """
    result = await session.execute(
        select(ProposalDB).where(ProposalDB.id == proposal_id)
    )
    proposal_row = result.scalar_one_or_none()
    if proposal_row is None:
        raise HTTPException(status_code=404, detail="Proposal not found")

    # Load the parent contract
    contract_result = await session.execute(
        select(ContractDB).where(ContractDB.id == proposal_row.contract_id)
    )
    contract_row = contract_result.scalar_one_or_none()
    if contract_row is None:
        raise HTTPException(status_code=404, detail="Contract not found")

    # This will be connected to Chrome MCP at runtime.
    return {
        "status": "ready",
        "message": "Form fill triggered. Ensure Chrome MCP is connected.",
        "proposal_id": proposal_id,
        "contract_id": proposal_row.contract_id,
    }
