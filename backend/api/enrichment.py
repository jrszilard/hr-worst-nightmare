"""Contract enrichment endpoints — AI-powered skill extraction and re-scoring."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.ai.contract_analyzer import analyze_contract
from backend.core.availability import get_availability
from backend.core.enums import ContractStatus
from backend.core.matching import calculate_match_score
from backend.core.models import AvailabilityConfig, Contract, LoadedProfile
from backend.core.scoring import assign_indicator, calculate_roi_score
from backend.core.profile_context import get_profile_context
from backend.db.database import get_session
from backend.db.models import ContractDB
from backend.portfolio.profile_loader import load_profile

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/contracts", tags=["enrichment"])


async def _enrich_contract(
    row: ContractDB,
    session: AsyncSession,
    profile: LoadedProfile,
    availability: AvailabilityConfig,
) -> dict:
    """Run AI analysis on a contract, update skills, description_fit, and scores."""
    contract = Contract.model_validate(row)

    # Run AI analysis
    analysis = await analyze_contract(
        title=contract.title or "",
        description=contract.description or "",
        skills_tags=contract.skills_required or [],
    )

    # Update skills and description fit
    row.skills_required = analysis.extracted_skills
    row.description_fit = analysis.description_fit_score

    # Re-score with new skills
    match_result = calculate_match_score(analysis.extracted_skills, profile)

    contract_for_scoring = Contract.model_validate(row)
    scoring = calculate_roi_score(match_result.match_score, contract_for_scoring, availability)

    # Recalculate win probability with description fit
    from backend.core.scoring import calculate_win_probability
    win_prob = calculate_win_probability(
        match_result.match_score,
        contract_for_scoring.client_hire_rate or 0.5,
        contract_for_scoring.proposals_count or 0,
        description_fit=analysis.description_fit_score,
    )

    row.match_score = match_result.match_score
    row.roi_score = scoring.roi_score

    # Re-evaluate auto-skip with description fit data
    import yaml
    from backend.api.scanner import determine_skip_reason
    profile_path = get_profile_context().profile_yaml
    profile_config = yaml.safe_load(profile_path.read_text(encoding="utf-8")) if profile_path.exists() else {}
    skip_threshold = profile_config.get("auto_skip_threshold", 0.15)

    combined_match = match_result.match_score * 0.4 + analysis.description_fit_score * 0.6
    skip_reason = determine_skip_reason(
        win_probability=win_prob,
        combined_match=combined_match,
        contract=contract_for_scoring,
        availability=availability,
        threshold=skip_threshold,
    )

    if skip_reason:
        row.status = ContractStatus.skipped
        row.skip_reason = skip_reason
    elif row.status == ContractStatus.skipped and row.skip_reason:
        # Un-skip if enrichment improved the score
        row.status = ContractStatus.new
        row.skip_reason = None

    await session.commit()
    await session.refresh(row)

    # Build response
    enriched = Contract.model_validate(row)
    all_result = await session.execute(
        select(ContractDB.roi_score).where(ContractDB.roi_score.isnot(None))
    )
    all_roi_scores = [r[0] for r in all_result.all()]
    data = enriched.model_dump()
    data["indicator"] = assign_indicator(enriched.roi_score or 0.0, all_roi_scores)
    return data


@router.post("/enrich/batch")
async def enrich_all_contracts(
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Batch-enrich all contracts missing skills.

    Processes contracts sequentially. Skips contracts that already have
    skills or that have no description. Returns a summary.
    """
    result = await session.execute(select(ContractDB))
    rows = result.scalars().all()

    # Load profile and availability once for the entire batch
    profile = load_profile()
    availability = await get_availability(session)

    enriched = 0
    skipped = 0
    failed = 0
    errors: list[str] = []

    for row in rows:
        # Skip if already has skills
        has_skills = row.skills_required and isinstance(row.skills_required, list) and len(row.skills_required) > 0
        if has_skills:
            skipped += 1
            continue

        # Skip if no description
        if not row.description:
            skipped += 1
            continue

        try:
            await _enrich_contract(row, session, profile, availability)
            enriched += 1
            logger.info("Batch enriched contract %d (%d/%d)",
                        row.id, enriched, len(rows))
        except Exception as exc:
            failed += 1
            error_msg = f"Contract {row.id}: {exc}"
            errors.append(error_msg)
            logger.warning("Failed to enrich contract %d: %s", row.id, exc)

    return {
        "enriched": enriched,
        "skipped": skipped,
        "failed": failed,
        "errors": errors,
    }


@router.post("/{contract_id}/enrich")
async def enrich_contract(
    contract_id: int,
    force: bool = Query(False),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Enrich a single contract with AI-extracted skills and re-score it.

    Skips contracts that already have skills unless ``force=true``.
    """
    result = await session.execute(
        select(ContractDB).where(ContractDB.id == contract_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Contract not found")

    # Skip if already enriched (unless forced)
    has_skills = row.skills_required and isinstance(row.skills_required, list) and len(row.skills_required) > 0
    if has_skills and not force:
        contract = Contract.model_validate(row)
        all_result = await session.execute(
            select(ContractDB.roi_score).where(ContractDB.roi_score.isnot(None))
        )
        all_roi_scores = [r[0] for r in all_result.all()]
        data = contract.model_dump()
        data["indicator"] = assign_indicator(contract.roi_score or 0.0, all_roi_scores)
        data["enrichment"] = "skipped"
        return data

    # Skip if no description to analyze
    if not row.description:
        raise HTTPException(status_code=422, detail="Contract has no description to analyze")

    profile = load_profile()
    availability = await get_availability(session)
    data = await _enrich_contract(row, session, profile, availability)
    data["enrichment"] = "completed"
    logger.info("Enriched contract %d: %d skills extracted, match=%.0f%%, roi=%.1f",
                contract_id, len(row.skills_required or []), row.match_score or 0, row.roi_score or 0)
    return data
