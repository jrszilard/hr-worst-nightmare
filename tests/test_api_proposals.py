"""Tests for the proposals API endpoints (and availability + history)."""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.ai.contract_analyzer import ContractAnalysis
from backend.ai.proposal_generator import GeneratedProposal
from backend.core.enums import ProposalSectionType
from backend.core.models import ProposalSection
from backend.db.models import (
    ApplicationHistoryDB,
    ApplicationOutcome,
    Base,
    ContractDB,
    ContractType,
    ProposalDB,
    ProposalStatus,
)


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
async def api_engine():
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture()
async def api_session_factory(api_engine):
    return async_sessionmaker(api_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture()
async def client(api_session_factory):
    from backend.db.database import get_session
    from backend.main import app

    async def _override_session():
        async with api_session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = _override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture()
async def seeded_contract(api_session_factory):
    """Insert a contract and return its ID."""
    async with api_session_factory() as session:
        c = ContractDB(
            platform="upwork",
            external_id="prop-test-1",
            title="Build a dashboard",
            description="Need a Power BI dashboard with real-time data.",
            skills_required=["Power BI", "SQL"],
            budget_min=500.0,
            budget_max=2000.0,
            contract_type=ContractType.fixed,
            roi_score=0.8,
            match_score=0.9,
            client_hire_rate=0.85,
            proposals_count=5,
            connects_cost=6,
        )
        session.add(c)
        await session.commit()
        await session.refresh(c)
        return c.id


@pytest.fixture()
async def seeded_proposal(api_session_factory, seeded_contract):
    """Insert a proposal and return its ID."""
    async with api_session_factory() as session:
        p = ProposalDB(
            contract_id=seeded_contract,
            version=1,
            content="I am excited to help.",
            sections=[
                {"type": "hook", "content": "Great opening.", "annotation": None},
                {"type": "experience", "content": "5 years.", "annotation": "strong"},
                {"type": "approach", "content": "My plan.", "annotation": None},
                {"type": "differentiator", "content": "Unique edge.", "annotation": None},
                {"type": "cta", "content": "Let's connect.", "annotation": None},
            ],
            matched_case_studies=["cs-1"],
            bid_amount=1500.0,
            estimated_duration="2 weeks",
            status=ProposalStatus.draft,
        )
        session.add(p)
        await session.commit()
        await session.refresh(p)
        return p.id


# ── POST /api/contracts/{id}/propose ────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_proposal(client, seeded_contract):
    """POST /api/contracts/{id}/propose orchestrates AI and saves proposal."""
    mock_analysis = ContractAnalysis(
        extracted_skills=["Power BI", "SQL"],
        skill_categories={"Power BI": "core", "SQL": "core"},
        client_problem="Need dashboard",
        implicit_needs=["real-time data"],
    )

    mock_generated = GeneratedProposal(
        sections=[
            ProposalSection(type=ProposalSectionType.hook, content="Great opening."),
            ProposalSection(type=ProposalSectionType.experience, content="5 years experience."),
            ProposalSection(type=ProposalSectionType.approach, content="My approach."),
            ProposalSection(type=ProposalSectionType.differentiator, content="Unique edge."),
            ProposalSection(type=ProposalSectionType.cta, content="Let's connect."),
        ],
        bid_amount=1500.0,
        estimated_duration="2 weeks",
    )

    with (
        patch(
            "backend.api.proposals.analyze_contract",
            new_callable=AsyncMock,
            return_value=mock_analysis,
        ),
        patch(
            "backend.api.proposals.generate_proposal",
            new_callable=AsyncMock,
            return_value=mock_generated,
        ),
    ):
        resp = await client.post(f"/api/contracts/{seeded_contract}/propose")

    assert resp.status_code == 200
    data = resp.json()
    assert data["contract_id"] == seeded_contract
    assert data["version"] == 1
    assert data["bid_amount"] == 1500.0
    assert data["estimated_duration"] == "2 weeks"
    assert len(data["sections"]) == 5
    assert data["sections"][0]["type"] == "hook"


@pytest.mark.asyncio
async def test_create_proposal_contract_not_found(client):
    """POST /api/contracts/9999/propose returns 404."""
    resp = await client.post("/api/contracts/9999/propose")
    assert resp.status_code == 404


# ── GET /api/proposals/{id} ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_proposal(client, seeded_proposal):
    """GET /api/proposals/{id} returns the proposal with sections."""
    resp = await client.get(f"/api/proposals/{seeded_proposal}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == seeded_proposal
    assert data["bid_amount"] == 1500.0
    assert len(data["sections"]) == 5


@pytest.mark.asyncio
async def test_get_proposal_not_found(client):
    """GET /api/proposals/9999 returns 404."""
    resp = await client.get("/api/proposals/9999")
    assert resp.status_code == 404


# ── PUT /api/proposals/{id} ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_proposal(client, seeded_proposal):
    """PUT /api/proposals/{id} updates content fields."""
    resp = await client.put(
        f"/api/proposals/{seeded_proposal}",
        json={"content": "Updated cover letter.", "bid_amount": 1200.0},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["content"] == "Updated cover letter."
    assert data["bid_amount"] == 1200.0


@pytest.mark.asyncio
async def test_update_proposal_not_found(client):
    """PUT /api/proposals/9999 returns 404."""
    resp = await client.put("/api/proposals/9999", json={"content": "x"})
    assert resp.status_code == 404


# ── POST /api/proposals/{id}/fill ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_fill_proposal(client, seeded_proposal):
    """POST /api/proposals/{id}/fill returns ready status."""
    resp = await client.post(f"/api/proposals/{seeded_proposal}/fill")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ready"
    assert data["proposal_id"] == seeded_proposal


@pytest.mark.asyncio
async def test_fill_proposal_not_found(client):
    """POST /api/proposals/9999/fill returns 404."""
    resp = await client.post("/api/proposals/9999/fill")
    assert resp.status_code == 404


# ── GET /api/availability ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_availability_defaults(client):
    """GET /api/availability returns default settings on first call."""
    resp = await client.get("/api/availability")
    assert resp.status_code == 200
    data = resp.json()
    assert data["hours_per_week"] == 40
    assert data["max_concurrent_contracts"] == 3
    assert data["min_hourly_rate"] == 75.0


# ── PUT /api/availability ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_availability(client):
    """PUT /api/availability updates and returns new settings."""
    update = {
        "hours_per_week": 30,
        "max_concurrent_contracts": 2,
        "current_committed_hours": 10,
        "preferred_duration": "short",
        "preferred_contract_type": "hourly",
        "min_hourly_rate": 100.0,
        "min_fixed_budget": 1000.0,
        "hourly_value": 120.0,
    }
    resp = await client.put("/api/availability", json=update)
    assert resp.status_code == 200
    data = resp.json()
    assert data["hours_per_week"] == 30
    assert data["min_hourly_rate"] == 100.0
    assert data["preferred_contract_type"] == "hourly"


# ── GET /api/history ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_history_empty(client):
    """GET /api/history returns empty list when no entries exist."""
    resp = await client.get("/api/history")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_create_and_list_history(client, seeded_proposal, seeded_contract):
    """POST /api/history creates an entry, GET /api/history returns it."""
    resp = await client.post(
        "/api/history",
        json={
            "contract_id": seeded_contract,
            "proposal_id": seeded_proposal,
            "connects_spent": 6,
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["contract_id"] == seeded_contract
    assert data["connects_spent"] == 6
    assert data["outcome"] == "submitted"

    # List
    resp = await client.get("/api/history")
    assert resp.status_code == 200
    entries = resp.json()
    assert len(entries) == 1


# ── GET /api/history/stats ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_history_stats_empty(client):
    """GET /api/history/stats returns zero stats when empty."""
    resp = await client.get("/api/history/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_applications"] == 0
    assert data["connects_spent"] == 0
    assert data["response_rate"] == 0.0
    assert data["outcomes_breakdown"] == {}


@pytest.mark.asyncio
async def test_history_stats_with_data(client, api_session_factory, seeded_proposal, seeded_contract):
    """GET /api/history/stats returns correct aggregates."""
    # Create two history entries
    async with api_session_factory() as session:
        e1 = ApplicationHistoryDB(
            contract_id=seeded_contract,
            proposal_id=seeded_proposal,
            connects_spent=6,
            outcome=ApplicationOutcome.submitted,
            submitted_at=datetime(2026, 3, 1),
        )
        e2 = ApplicationHistoryDB(
            contract_id=seeded_contract,
            proposal_id=seeded_proposal,
            connects_spent=4,
            outcome=ApplicationOutcome.interview,
            submitted_at=datetime(2026, 3, 5),
        )
        session.add_all([e1, e2])
        await session.commit()

    resp = await client.get("/api/history/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_applications"] == 2
    assert data["connects_spent"] == 10
    assert data["response_rate"] == 0.5  # 1 interview out of 2
    assert data["outcomes_breakdown"]["submitted"] == 1
    assert data["outcomes_breakdown"]["interview"] == 1
