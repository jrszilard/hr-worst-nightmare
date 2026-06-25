"""Tests for the contracts API endpoints."""

from datetime import datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.db.models import Base, ContractDB, ContractStatus, ContractType


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
async def api_engine():
    """In-memory engine for API tests."""
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture()
async def api_session_factory(api_engine):
    """Session factory bound to the test engine."""
    return async_sessionmaker(api_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture()
async def client(api_session_factory):
    """Async HTTP client wired to a fresh in-memory database."""
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
async def seeded_client(api_session_factory, client):
    """Client with pre-seeded contracts."""
    async with api_session_factory() as session:
        contracts = [
            ContractDB(
                platform="upwork",
                external_id="c1",
                title="Power BI Dashboard",
                skills_required=["Power BI", "SQL"],
                budget_min=500.0,
                budget_max=2000.0,
                contract_type=ContractType.fixed,
                roi_score=0.9,
                match_score=0.85,
                status=ContractStatus.new,
                client_hire_rate=0.8,
                proposals_count=5,
                connects_cost=6,
                posted_at=datetime(2026, 3, 1),
            ),
            ContractDB(
                platform="upwork",
                external_id="c2",
                title="Python Automation",
                skills_required=["Python", "Automation"],
                budget_min=100.0,
                budget_max=500.0,
                contract_type=ContractType.hourly,
                roi_score=0.5,
                match_score=0.6,
                status=ContractStatus.reviewed,
                client_hire_rate=0.7,
                proposals_count=10,
                connects_cost=4,
                posted_at=datetime(2026, 3, 5),
            ),
            ContractDB(
                platform="upwork",
                external_id="c3",
                title="Data Pipeline",
                skills_required=["Python", "SQL", "Data Engineering"],
                budget_min=1000.0,
                budget_max=5000.0,
                contract_type=ContractType.fixed,
                roi_score=0.3,
                match_score=0.4,
                status=ContractStatus.new,
                client_hire_rate=0.5,
                proposals_count=20,
                connects_cost=8,
                posted_at=datetime(2026, 3, 10),
            ),
        ]
        session.add_all(contracts)
        await session.commit()
    yield client


# ── GET /api/contracts ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_contracts_empty(client):
    """Empty database returns an empty list."""
    resp = await client.get("/api/contracts")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_contracts_sorted_by_roi(seeded_client):
    """Contracts are returned sorted by roi_score descending."""
    resp = await seeded_client.get("/api/contracts")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3
    roi_scores = [c["roi_score"] for c in data]
    assert roi_scores == sorted(roi_scores, reverse=True)


@pytest.mark.asyncio
async def test_list_contracts_has_indicator(seeded_client):
    """Each contract in the response has an indicator field."""
    resp = await seeded_client.get("/api/contracts")
    data = resp.json()
    for contract in data:
        assert "indicator" in contract
        assert contract["indicator"] in ("green", "yellow", "red")


@pytest.mark.asyncio
async def test_list_contracts_filter_status(seeded_client):
    """Filter by status query param."""
    resp = await seeded_client.get("/api/contracts", params={"status": "reviewed"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["external_id"] == "c2"


@pytest.mark.asyncio
async def test_list_contracts_filter_contract_type(seeded_client):
    """Filter by contract_type query param."""
    resp = await seeded_client.get("/api/contracts", params={"contract_type": "hourly"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["contract_type"] == "hourly"


@pytest.mark.asyncio
async def test_list_contracts_filter_min_roi(seeded_client):
    """Filter by min_roi query param."""
    resp = await seeded_client.get("/api/contracts", params={"min_roi": 0.45})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    for c in data:
        assert c["roi_score"] >= 0.45


@pytest.mark.asyncio
async def test_list_contracts_filter_budget_min(seeded_client):
    """Filter by budget_min query param."""
    resp = await seeded_client.get("/api/contracts", params={"budget_min": 500})
    assert resp.status_code == 200
    data = resp.json()
    # c1 has budget_min=500, c3 has budget_min=1000; c2 has budget_min=100
    assert len(data) == 2


@pytest.mark.asyncio
async def test_list_contracts_filter_budget_max(seeded_client):
    """Filter by budget_max query param."""
    resp = await seeded_client.get("/api/contracts", params={"budget_max": 2000})
    assert resp.status_code == 200
    data = resp.json()
    # c1 has budget_max=2000, c2 has budget_max=500
    assert len(data) == 2


@pytest.mark.asyncio
async def test_list_contracts_filter_skill(seeded_client):
    """Filter by skill query param (substring match in skills_required)."""
    resp = await seeded_client.get("/api/contracts", params={"skill": "SQL"})
    assert resp.status_code == 200
    data = resp.json()
    # c1 has SQL, c3 has SQL; c2 does not
    assert len(data) == 2


# ── GET /api/contracts/{id} ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_contract_by_id(seeded_client):
    """Retrieve a single contract by ID."""
    # First list to get an ID
    resp = await seeded_client.get("/api/contracts")
    contract_id = resp.json()[0]["id"]

    resp = await seeded_client.get(f"/api/contracts/{contract_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == contract_id
    assert "indicator" in data


@pytest.mark.asyncio
async def test_get_contract_not_found(client):
    """404 for non-existent contract."""
    resp = await client.get("/api/contracts/9999")
    assert resp.status_code == 404
