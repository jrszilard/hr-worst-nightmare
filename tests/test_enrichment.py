"""Tests for the contract enrichment endpoints."""

from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.db.models import Base, ContractDB, ContractStatus, ContractType


# ── Fixtures ──────────────────────────────────────────────────────────────


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


def _mock_claude_response(skills: list[str]) -> AsyncMock:
    """Build a mock Anthropic client returning extracted skills."""
    text = json.dumps({
        "extracted_skills": skills,
        "client_problem": "Client needs help.",
        "implicit_needs": ["Testing"],
    })
    content_block = SimpleNamespace(text=text)
    response = SimpleNamespace(content=[content_block])
    client = AsyncMock()
    client.messages.create = AsyncMock(return_value=response)
    return client


# ── Single-contract enrichment ────────────────────────────────────────────


async def test_enrich_contract_extracts_skills(api_session_factory, client):
    """Contract with no skills gets AI-extracted skills and re-scored."""
    async with api_session_factory() as session:
        row = ContractDB(
            platform="upwork", external_id="no-skills-1",
            title="Data Pipeline Developer",
            description="Build ETL pipelines using Python and SQL for analytics.",
            contract_type=ContractType.fixed, budget_max=5000.0,
            client_hire_rate=0.8, proposals_count=10, connects_cost=12,
            skills_required=None, match_score=0.0, roi_score=0.0,
            status=ContractStatus.new, posted_at=datetime(2026, 4, 1),
        )
        session.add(row)
        await session.commit()
        contract_id = row.id

    mock_client = _mock_claude_response(["Python", "SQL", "ETL"])

    with patch("backend.ai.contract_analyzer.anthropic.AsyncAnthropic", return_value=mock_client):
        resp = await client.post(f"/api/contracts/{contract_id}/enrich")

    assert resp.status_code == 200
    data = resp.json()
    assert data["enrichment"] == "completed"
    assert data["skills_required"] == ["Python", "SQL", "ETL"]
    assert data["match_score"] > 0.0
    assert data["roi_score"] > 0.0


async def test_enrich_skips_already_enriched(api_session_factory, client):
    """Contract with existing skills is skipped (no AI call)."""
    async with api_session_factory() as session:
        row = ContractDB(
            platform="upwork", external_id="has-skills-1",
            title="Power BI Dashboard",
            description="Build a dashboard.",
            skills_required=["Power BI", "SQL"],
            match_score=0.8, roi_score=5.0,
            status=ContractStatus.new, posted_at=datetime(2026, 4, 1),
        )
        session.add(row)
        await session.commit()
        contract_id = row.id

    resp = await client.post(f"/api/contracts/{contract_id}/enrich")

    assert resp.status_code == 200
    data = resp.json()
    assert data["enrichment"] == "skipped"
    assert data["skills_required"] == ["Power BI", "SQL"]


async def test_enrich_force_re_enriches(api_session_factory, client):
    """With force=true, contract is re-enriched even if skills exist."""
    async with api_session_factory() as session:
        row = ContractDB(
            platform="upwork", external_id="force-1",
            title="AI Agent Developer",
            description="Build AI agents using LangChain and Python.",
            skills_required=["Python"],
            contract_type=ContractType.fixed, budget_max=3000.0,
            client_hire_rate=0.7, proposals_count=8, connects_cost=10,
            match_score=0.5, roi_score=1.0,
            status=ContractStatus.new, posted_at=datetime(2026, 4, 1),
        )
        session.add(row)
        await session.commit()
        contract_id = row.id

    mock_client = _mock_claude_response(["Python", "LangChain", "AI Agents"])

    with patch("backend.ai.contract_analyzer.anthropic.AsyncAnthropic", return_value=mock_client):
        resp = await client.post(f"/api/contracts/{contract_id}/enrich?force=true")

    assert resp.status_code == 200
    data = resp.json()
    assert data["enrichment"] == "completed"
    assert "LangChain" in data["skills_required"]


async def test_enrich_404_missing_contract(client):
    """Enriching a non-existent contract returns 404."""
    resp = await client.post("/api/contracts/99999/enrich")
    assert resp.status_code == 404


async def test_enrich_422_no_description(api_session_factory, client):
    """Contract with no description returns 422."""
    async with api_session_factory() as session:
        row = ContractDB(
            platform="upwork", external_id="no-desc-1",
            title="Some Job", description=None,
            skills_required=None,
            status=ContractStatus.new, posted_at=datetime(2026, 4, 1),
        )
        session.add(row)
        await session.commit()
        contract_id = row.id

    resp = await client.post(f"/api/contracts/{contract_id}/enrich")
    assert resp.status_code == 422


# ── Batch enrichment ──────────────────────────────────────────────────────


async def test_batch_enrich_processes_missing_skills(api_session_factory, client):
    """Batch endpoint enriches contracts without skills, skips ones that have them."""
    async with api_session_factory() as session:
        # Contract WITH skills — should be skipped
        session.add(ContractDB(
            platform="upwork", external_id="batch-has-skills",
            title="Existing Skills", description="Already enriched.",
            skills_required=["Python"], match_score=0.5, roi_score=2.0,
            status=ContractStatus.new, posted_at=datetime(2026, 4, 1),
        ))
        # Contract WITHOUT skills — should be enriched
        session.add(ContractDB(
            platform="upwork", external_id="batch-no-skills",
            title="Needs Enrichment",
            description="Build a data pipeline using Python and PostgreSQL.",
            skills_required=None, match_score=0.0, roi_score=0.0,
            contract_type=ContractType.fixed, budget_max=4000.0,
            client_hire_rate=0.9, proposals_count=5, connects_cost=8,
            status=ContractStatus.new, posted_at=datetime(2026, 4, 1),
        ))
        # Contract WITHOUT skills AND no description — should be skipped
        session.add(ContractDB(
            platform="upwork", external_id="batch-no-desc",
            title="No Description", description=None,
            skills_required=None,
            status=ContractStatus.new, posted_at=datetime(2026, 4, 1),
        ))
        await session.commit()

    mock_client = _mock_claude_response(["Python", "PostgreSQL"])

    with patch("backend.ai.contract_analyzer.anthropic.AsyncAnthropic", return_value=mock_client):
        resp = await client.post("/api/contracts/enrich/batch")

    assert resp.status_code == 200
    data = resp.json()
    assert data["enriched"] == 1
    assert data["skipped"] == 2
    assert data["failed"] == 0
    assert data["errors"] == []


async def test_batch_enrich_handles_ai_failure(api_session_factory, client):
    """Batch endpoint continues past individual AI failures."""
    async with api_session_factory() as session:
        session.add(ContractDB(
            platform="upwork", external_id="batch-fail-1",
            title="Will Fail",
            description="Some description that will cause AI to fail.",
            skills_required=None,
            contract_type=ContractType.fixed, budget_max=2000.0,
            status=ContractStatus.new, posted_at=datetime(2026, 4, 1),
        ))
        await session.commit()

    # Mock Claude to raise an error
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(side_effect=Exception("API rate limit"))

    with patch("backend.ai.contract_analyzer.anthropic.AsyncAnthropic", return_value=mock_client):
        resp = await client.post("/api/contracts/enrich/batch")

    assert resp.status_code == 200
    data = resp.json()
    assert data["enriched"] == 0
    assert data["failed"] == 1
    assert len(data["errors"]) == 1
    assert "API rate limit" in data["errors"][0]


async def test_batch_enrich_empty_database(client):
    """Batch enrichment on empty database returns zeros."""
    resp = await client.post("/api/contracts/enrich/batch")
    assert resp.status_code == 200
    data = resp.json()
    assert data["enriched"] == 0
    assert data["skipped"] == 0
    assert data["failed"] == 0


@pytest.mark.asyncio
async def test_enrich_stores_description_fit_and_skips(client, api_session_factory):
    """Enrichment should store description_fit and auto-skip low-fit contracts."""
    # Insert a contract with no skills (needs enrichment)
    async with api_session_factory() as session:
        row = ContractDB(
            platform="upwork",
            external_id="~skip-test",
            title="Rust Systems Programmer",
            description="We need a senior Rust developer to build a high-performance systems library. Must have 5+ years Rust experience with unsafe code, FFI, and memory management.",
            contract_type=ContractType.fixed,
            budget_max=5000,
            client_hire_rate=0.8,
            proposals_count=10,
            status=ContractStatus.new,
        )
        session.add(row)
        await session.commit()
        contract_id = row.id

    # Mock the AI analyzer to return low description fit
    mock_analysis = SimpleNamespace(
        extracted_skills=["Rust", "FFI", "Memory Management"],
        skill_categories={"Rust": "unmatched", "FFI": "unmatched", "Memory Management": "unmatched"},
        client_problem="Need a Rust developer",
        implicit_needs=["Testing", "Documentation"],
        description_fit_score=0.1,
    )

    with patch("backend.api.enrichment.analyze_contract", new_callable=AsyncMock, return_value=mock_analysis), \
         patch("backend.api.enrichment.load_profile") as mock_profile:
        from backend.portfolio.profile_loader import load_profile as real_load
        mock_profile.return_value = real_load()

        resp = await client.post(f"/api/contracts/{contract_id}/enrich?force=true")
        assert resp.status_code == 200
        data = resp.json()

        # Should have stored description_fit
        assert data.get("description_fit") == 0.1

        # Should have been auto-skipped due to low match
        assert data.get("status") == "skipped"
        assert data.get("skip_reason") is not None
