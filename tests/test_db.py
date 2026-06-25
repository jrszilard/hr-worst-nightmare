"""Tests for database models and CRUD operations."""

from datetime import datetime

import pytest
from sqlalchemy import inspect, select

from backend.db.models import (
    ApplicationHistoryDB,
    ApplicationOutcome,
    Base,
    ContractDB,
    ContractStatus,
    ContractType,
    ProposalDB,
    ProposalStatus,
)


# ── Table creation ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tables_are_created(db_engine):
    """All expected tables exist after create_all."""
    async with db_engine.connect() as conn:
        table_names = await conn.run_sync(
            lambda sync_conn: inspect(sync_conn).get_table_names()
        )
    expected = {"contracts", "proposals", "application_history"}
    assert expected.issubset(set(table_names))


@pytest.mark.asyncio
async def test_contract_unique_constraint_columns(db_engine):
    """The contracts table has a unique constraint on (platform, external_id)."""
    async with db_engine.connect() as conn:
        unique_constraints = await conn.run_sync(
            lambda sync_conn: inspect(sync_conn).get_unique_constraints("contracts")
        )
    col_sets = [set(uc["column_names"]) for uc in unique_constraints]
    assert {"platform", "external_id"} in col_sets


# ── Contract CRUD & upsert ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_contract(db_session):
    """Insert a contract and read it back."""
    contract = ContractDB(
        platform="upwork",
        external_id="abc123",
        url="https://upwork.com/jobs/abc123",
        title="Build a dashboard",
        description="Need a Power BI dashboard.",
        skills_required=["Power BI", "SQL"],
        budget_min=500.0,
        budget_max=2000.0,
        contract_type=ContractType.fixed,
        duration="1-3 months",
        proposals_count=5,
        client_hire_rate=0.85,
        client_total_spent=50000.0,
        client_location="US",
        match_score=0.92,
        roi_score=0.78,
        connects_cost=6,
        client_questions=["What is your experience?"],
        status=ContractStatus.new,
        posted_at=datetime(2026, 3, 1),
        fetched_at=datetime(2026, 3, 19),
    )
    db_session.add(contract)
    await db_session.commit()

    result = await db_session.execute(
        select(ContractDB).where(ContractDB.external_id == "abc123")
    )
    row = result.scalar_one()
    assert row.platform == "upwork"
    assert row.title == "Build a dashboard"
    assert row.skills_required == ["Power BI", "SQL"]
    assert row.status == ContractStatus.new


@pytest.mark.asyncio
async def test_contract_upsert_preserves_status(db_session):
    """Re-inserting the same (platform, external_id) should update metadata but keep user-managed status."""
    # Insert original contract
    original = ContractDB(
        platform="upwork",
        external_id="upsert-test",
        title="Original Title",
        description="Original description",
        status=ContractStatus.new,
        budget_min=100.0,
        fetched_at=datetime(2026, 3, 1),
    )
    db_session.add(original)
    await db_session.commit()

    # Simulate user reviewing the contract
    original.status = ContractStatus.reviewed
    await db_session.commit()

    # Simulate a re-scan: look up existing, update metadata, preserve status
    result = await db_session.execute(
        select(ContractDB).where(
            ContractDB.platform == "upwork",
            ContractDB.external_id == "upsert-test",
        )
    )
    existing = result.scalar_one()
    assert existing.status == ContractStatus.reviewed

    # Update metadata fields (as a scanner would do)
    existing.title = "Updated Title"
    existing.description = "Updated description"
    existing.budget_min = 200.0
    existing.fetched_at = datetime(2026, 3, 19)
    # status is NOT overwritten
    await db_session.commit()

    # Verify
    result2 = await db_session.execute(
        select(ContractDB).where(ContractDB.external_id == "upsert-test")
    )
    refreshed = result2.scalar_one()
    assert refreshed.title == "Updated Title"
    assert refreshed.budget_min == 200.0
    assert refreshed.status == ContractStatus.reviewed  # preserved


@pytest.mark.asyncio
async def test_contract_duplicate_raises(db_session):
    """Inserting two contracts with same (platform, external_id) raises IntegrityError."""
    from sqlalchemy.exc import IntegrityError

    c1 = ContractDB(platform="upwork", external_id="dup1", title="First")
    c2 = ContractDB(platform="upwork", external_id="dup1", title="Second")
    db_session.add(c1)
    await db_session.commit()

    db_session.add(c2)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


# ── Proposal CRUD ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_proposal_crud(db_session):
    """Create, read, update, delete a proposal."""
    # Setup: create parent contract
    contract = ContractDB(
        platform="upwork", external_id="prop-test", title="Proposal test contract"
    )
    db_session.add(contract)
    await db_session.commit()

    # Create
    proposal = ProposalDB(
        contract_id=contract.id,
        version=1,
        content="I am excited to help with your project.",
        sections=[
            {"type": "hook", "content": "Great opening line.", "annotation": None},
            {"type": "experience", "content": "5 years of BI work.", "annotation": "strong match", "case_study_ids": ["cs-1"]},
        ],
        matched_case_studies=["cs-1"],
        bid_amount=1500.0,
        estimated_duration="2 weeks",
        status=ProposalStatus.draft,
    )
    db_session.add(proposal)
    await db_session.commit()

    # Read
    result = await db_session.execute(
        select(ProposalDB).where(ProposalDB.contract_id == contract.id)
    )
    fetched = result.scalar_one()
    assert fetched.version == 1
    assert fetched.bid_amount == 1500.0
    assert fetched.status == ProposalStatus.draft
    assert len(fetched.sections) == 2
    assert fetched.sections[0]["type"] == "hook"

    # Update
    fetched.status = ProposalStatus.approved
    fetched.bid_amount = 1400.0
    await db_session.commit()

    result2 = await db_session.execute(select(ProposalDB).where(ProposalDB.id == fetched.id))
    updated = result2.scalar_one()
    assert updated.status == ProposalStatus.approved
    assert updated.bid_amount == 1400.0

    # Delete
    await db_session.delete(updated)
    await db_session.commit()

    result3 = await db_session.execute(
        select(ProposalDB).where(ProposalDB.contract_id == contract.id)
    )
    assert result3.scalar_one_or_none() is None


# ── ApplicationHistory CRUD ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_application_history_crud(db_session):
    """Create, read, update, delete an application history entry."""
    # Setup: create contract + proposal
    contract = ContractDB(
        platform="upwork", external_id="app-hist-test", title="App history test"
    )
    db_session.add(contract)
    await db_session.commit()

    proposal = ProposalDB(
        contract_id=contract.id, version=1, content="Proposal text", status=ProposalStatus.draft
    )
    db_session.add(proposal)
    await db_session.commit()

    # Create
    app_hist = ApplicationHistoryDB(
        contract_id=contract.id,
        proposal_id=proposal.id,
        connects_spent=6,
        outcome=ApplicationOutcome.submitted,
        submitted_at=datetime(2026, 3, 19),
    )
    db_session.add(app_hist)
    await db_session.commit()

    # Read
    result = await db_session.execute(
        select(ApplicationHistoryDB).where(ApplicationHistoryDB.contract_id == contract.id)
    )
    fetched = result.scalar_one()
    assert fetched.connects_spent == 6
    assert fetched.outcome == ApplicationOutcome.submitted
    assert fetched.outcome_at is None

    # Update — simulate interview outcome
    fetched.outcome = ApplicationOutcome.interview
    fetched.outcome_at = datetime(2026, 3, 25)
    await db_session.commit()

    result2 = await db_session.execute(
        select(ApplicationHistoryDB).where(ApplicationHistoryDB.id == fetched.id)
    )
    updated = result2.scalar_one()
    assert updated.outcome == ApplicationOutcome.interview
    assert updated.outcome_at == datetime(2026, 3, 25)

    # Delete
    await db_session.delete(updated)
    await db_session.commit()

    result3 = await db_session.execute(
        select(ApplicationHistoryDB).where(ApplicationHistoryDB.contract_id == contract.id)
    )
    assert result3.scalar_one_or_none() is None
