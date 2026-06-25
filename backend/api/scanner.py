"""Scanner control API endpoints."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks
from sqlalchemy import select

from backend.core.enums import ContractStatus, ContractType, ScannerState
from backend.core.matching import calculate_match_score
from backend.core.models import AvailabilityConfig, Contract, ContractCreate, ScannerStatus
from backend.core.scoring import calculate_roi_score
from backend.db.database import async_session
from backend.db.models import ContractDB
from backend.core.profile_context import get_profile_context
from backend.portfolio.profile_loader import load_profile

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/scanner", tags=["scanner"])

def determine_skip_reason(
    win_probability: float,
    combined_match: float,
    contract,
    availability,
    threshold: float = 0.15,
) -> str | None:
    """Return a skip reason if the contract should be auto-skipped, else None.

    Priority order: low_budget > low_match > low_client_quality > high_competition.
    """
    reasons: list[str] = []

    # Check budget floor
    budget_max = getattr(contract, 'budget_max', None)
    contract_type = getattr(contract, 'contract_type', None)
    if budget_max is not None and contract_type is not None:
        ct_value = contract_type.value if hasattr(contract_type, 'value') else str(contract_type)
        if ct_value == "hourly" and budget_max < availability.min_hourly_rate:
            reasons.append("low_budget")
        elif ct_value == "fixed" and budget_max < availability.min_fixed_budget:
            reasons.append("low_budget")

    if combined_match < 0.25:
        reasons.append("low_match")

    hire_rate = getattr(contract, 'client_hire_rate', None)
    spent = getattr(contract, 'client_total_spent', None) or 0
    if (hire_rate is not None and hire_rate < 0.20) or spent == 0:
        reasons.append("low_client_quality")

    proposals = getattr(contract, 'proposals_count', None) or 0
    if proposals > 30:
        reasons.append("high_competition")

    if not reasons and win_probability >= threshold:
        return None

    # Return highest priority reason
    priority = ["low_budget", "low_match", "low_client_quality", "high_competition"]
    for reason in priority:
        if reason in reasons:
            return reason

    # Win prob below threshold but no specific reason
    if win_probability < threshold:
        return "low_match"

    return None


# In-memory scanner status — fine for V1 since this is a single-user app.
_scanner_status = ScannerStatus()


def get_scanner_status() -> ScannerStatus:
    """Return the current scanner status (for use in tests or other modules)."""
    return _scanner_status


def reset_scanner_status() -> None:
    """Reset the scanner status to idle (for testing)."""
    global _scanner_status
    _scanner_status = ScannerStatus()


def _load_search_config() -> dict:
    """Load search configuration from <PROFILE_DIR>/searches.yaml."""
    import yaml
    searches_path = get_profile_context().searches_yaml
    if searches_path.exists():
        return yaml.safe_load(searches_path.read_text(encoding="utf-8"))
    return {"searches": [{"query": "AI data analysis python"}]}


async def _persist_contract(contract: ContractCreate, profile: dict, avail: AvailabilityConfig) -> bool:
    """Score and insert a single contract into the DB. Returns True if inserted."""
    async with async_session() as session:
        # Skip duplicates
        existing = await session.execute(
            select(ContractDB).where(ContractDB.external_id == contract.external_id)
        )
        if existing.scalar_one_or_none():
            return False

        # Calculate match score
        skills = contract.skills_required or []
        match_result = calculate_match_score(skills, profile) if skills else None
        match_score = match_result.match_score if match_result else 0.0

        # Calculate ROI score
        contract_for_scoring = Contract(
            id=0, platform=contract.platform, external_id=contract.external_id,
            title=contract.title, description=contract.description,
            budget_min=contract.budget_min, budget_max=contract.budget_max,
            contract_type=contract.contract_type.value if contract.contract_type else "fixed",
            client_hire_rate=contract.client_hire_rate or 0.5,
            proposals_count=contract.proposals_count or 20,
            connects_cost=contract.connects_cost or 16,
            client_total_spent=contract.client_total_spent,
        )
        scoring = calculate_roi_score(match_score, contract_for_scoring, avail)

        # Load skip threshold from profile config
        import yaml
        profile_path = get_profile_context().profile_yaml
        profile_config = yaml.safe_load(profile_path.read_text(encoding="utf-8")) if profile_path.exists() else {}
        skip_threshold = profile_config.get("auto_skip_threshold", 0.15)

        # Determine skip reason
        skip_reason = determine_skip_reason(
            win_probability=scoring.win_probability,
            combined_match=match_score,
            contract=contract,
            availability=avail,
            threshold=skip_threshold,
        )
        initial_status = ContractStatus.skipped if skip_reason else ContractStatus.new

        row = ContractDB(
            platform=contract.platform,
            external_id=contract.external_id,
            url=contract.url,
            title=contract.title,
            description=contract.description,
            skills_required=skills if skills else None,
            budget_min=contract.budget_min,
            budget_max=contract.budget_max,
            contract_type=ContractType(contract.contract_type) if contract.contract_type else None,
            duration=contract.duration,
            proposals_count=contract.proposals_count,
            client_hire_rate=contract.client_hire_rate,
            client_total_spent=contract.client_total_spent,
            client_location=contract.client_location,
            match_score=match_score,
            roi_score=scoring.roi_score,
            connects_cost=contract.connects_cost,
            status=initial_status,
            source=contract.source,
            skip_reason=skip_reason,
            posted_at=contract.posted_at or datetime.now(UTC),
            fetched_at=datetime.now(UTC),
        )
        session.add(row)
        await session.commit()
        return True


async def _run_scan() -> None:
    """Execute a Playwright-based contract scan in the background.

    Loads search config from data/searches.yaml, navigates Upwork search
    pages, extracts listing data, scores each contract, and inserts into
    the database.
    """
    global _scanner_status
    _scanner_status.state = ScannerState.running
    _scanner_status.started_at = datetime.now(UTC)
    _scanner_status.errors = []
    _scanner_status.contracts_found = 0
    _scanner_status.progress = 0.0

    try:
        from backend.platforms.upwork.playwright_scanner import run_playwright_scan

        search_config = _load_search_config()
        searches = search_config.get("searches", [])
        total_searches = len(searches) or 1

        profile = load_profile()
        avail = AvailabilityConfig()
        found_contracts: list[ContractCreate] = []

        def on_contract(contract: ContractCreate) -> None:
            found_contracts.append(contract)

        _scanner_status.current_search = "starting scan"
        _scanner_status.progress = 0.05

        total = await run_playwright_scan(search_config, on_contract)
        _scanner_status.progress = 0.5
        _scanner_status.current_search = "scoring and inserting"

        # Persist all found contracts with scoring
        inserted = 0
        for i, contract in enumerate(found_contracts):
            try:
                was_inserted = await _persist_contract(contract, profile, avail)
                if was_inserted:
                    inserted += 1
            except Exception:
                logger.exception("Failed to persist contract: %s", contract.external_id)

            _scanner_status.contracts_found = inserted
            _scanner_status.progress = 0.5 + (0.5 * (i + 1) / len(found_contracts)) if found_contracts else 1.0

        _scanner_status.progress = 1.0
        _scanner_status.state = ScannerState.complete
        _scanner_status.current_search = None
        _scanner_status.contracts_found = inserted
        logger.info("Scan complete: %d found, %d new inserted", total, inserted)

    except Exception as exc:
        logger.exception("Scanner failed")
        _scanner_status.state = ScannerState.error
        _scanner_status.errors.append(str(exc))


@router.post("/scan")
async def start_scan(background_tasks: BackgroundTasks) -> dict:
    """Launch a Chrome scan as a background task.

    Returns immediately with ``{"state": "running"}``.
    All scanner state initialization is handled by ``_run_scan``.
    """
    if _scanner_status.state == ScannerState.running:
        return {"state": "running", "message": "Scan already in progress"}

    background_tasks.add_task(_run_scan)
    return {"state": "running"}


@router.get("/status")
async def scanner_status() -> ScannerStatus:
    """Return the current scanner status."""
    return _scanner_status


# ---------------------------------------------------------------------------
# Job-board scan (Greenhouse/Lever public APIs) — mirrors the Upwork scan above.
# ---------------------------------------------------------------------------

import httpx

from backend.core.board_scan import load_board_config, scan_job_boards
from backend.platforms.ashby.board_client import jobs_url as ashby_jobs_url
from backend.platforms.greenhouse.board_client import jobs_url as gh_jobs_url
from backend.platforms.lever.board_client import postings_url as lever_postings_url

_job_scanner_status = ScannerStatus()


def get_job_scanner_status() -> ScannerStatus:
    return _job_scanner_status


def reset_job_scanner_status() -> None:
    global _job_scanner_status
    _job_scanner_status = ScannerStatus()


async def _fetch_board(vendor: str, slug: str):
    if vendor == "greenhouse":
        url = gh_jobs_url(slug)
    elif vendor == "ashby":
        url = ashby_jobs_url(slug)
    else:
        url = lever_postings_url(slug)
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url, headers={"Accept": "application/json"})
        resp.raise_for_status()
        return resp.json()


def _job_skip_threshold() -> float:
    import yaml
    path = get_profile_context().profile_yaml
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    return float(data.get("auto_skip_threshold", 0.15))


async def _run_job_scan() -> None:
    """Background: scan configured boards and ingest jobs."""
    global _job_scanner_status
    _job_scanner_status.state = ScannerState.running
    _job_scanner_status.started_at = datetime.now(UTC)
    _job_scanner_status.errors = []
    _job_scanner_status.contracts_found = 0
    _job_scanner_status.progress = 0.1
    _job_scanner_status.current_search = "scanning job boards"
    try:
        config = load_board_config()
        async with async_session() as session:
            summary = await scan_job_boards(
                session, config=config, fetch=_fetch_board, threshold=_job_skip_threshold(),
            )
            await session.commit()
        _job_scanner_status.contracts_found = summary.get("total", 0)
        _job_scanner_status.errors = summary.get("errors", [])
        _job_scanner_status.progress = 1.0
        _job_scanner_status.state = ScannerState.complete
    except Exception as exc:  # noqa: BLE001
        logger.exception("Job board scan failed")
        _job_scanner_status.errors = [str(exc)]
        _job_scanner_status.state = ScannerState.error


@router.post("/jobs")
async def start_job_scan(background_tasks: BackgroundTasks) -> ScannerStatus:
    if _job_scanner_status.state != ScannerState.running:
        reset_job_scanner_status()
        _job_scanner_status.state = ScannerState.running
        background_tasks.add_task(_run_job_scan)
    return _job_scanner_status


@router.get("/jobs/status")
async def job_scan_status() -> ScannerStatus:
    return _job_scanner_status


# ---------------------------------------------------------------------------
# JSearch discovery — mirrors the job-board scan above.
# ---------------------------------------------------------------------------

from backend.core.job_search import load_search_config, search_jobs  # noqa: E402
from backend.platforms.jsearch.client import fetch_jsearch  # noqa: E402

_job_search_status = ScannerStatus()


def get_job_search_status() -> ScannerStatus:
    return _job_search_status


def reset_job_search_status() -> None:
    global _job_search_status
    _job_search_status = ScannerStatus()


async def _run_job_search() -> None:
    """Background: run JSearch discovery and ingest jobs."""
    global _job_search_status
    _job_search_status.state = ScannerState.running
    _job_search_status.started_at = datetime.now(UTC)
    _job_search_status.errors = []
    _job_search_status.contracts_found = 0
    _job_search_status.progress = 0.1
    _job_search_status.current_search = "searching JSearch"
    try:
        config = load_search_config()
        async with async_session() as session:
            summary = await search_jobs(
                session, config=config, fetch=fetch_jsearch, threshold=_job_skip_threshold(),
            )
            await session.commit()
        _job_search_status.contracts_found = summary.get("total", 0)
        _job_search_status.errors = [str(e) for e in summary.get("errors", [])]
        _job_search_status.progress = 1.0
        _job_search_status.state = ScannerState.complete
    except Exception as exc:  # noqa: BLE001
        logger.exception("JSearch discovery failed")
        _job_search_status.errors = [str(exc)]
        _job_search_status.state = ScannerState.error


@router.post("/search")
async def start_job_search(background_tasks: BackgroundTasks) -> ScannerStatus:
    if _job_search_status.state != ScannerState.running:
        reset_job_search_status()
        _job_search_status.state = ScannerState.running
        background_tasks.add_task(_run_job_search)
    return _job_search_status


@router.get("/search/status")
async def job_search_status() -> ScannerStatus:
    return _job_search_status
