"""End-to-end integration tests for the contract-finder pipeline.

These tests exercise full request flows through the FastAPI app, hitting
real database operations (in-memory SQLite) with mocked AI services.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.ai.contract_analyzer import ContractAnalysis
from backend.ai.proposal_generator import GeneratedProposal
from backend.core.enums import ContractType, ProposalSectionType
from backend.core.models import ProposalSection
from backend.db.models import Base, ContractDB


# ── Shared fixtures ──────────────────────────────────────────────────────────


@pytest.fixture()
async def api_engine():
    """In-memory engine shared across integration tests."""
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


# ── Mock helpers ─────────────────────────────────────────────────────────────


def _mock_analysis(skills: list[str] | None = None) -> ContractAnalysis:
    """Build a mock ContractAnalysis with sensible defaults."""
    extracted = skills or ["Power BI", "SQL", "DAX"]
    return ContractAnalysis(
        extracted_skills=extracted,
        skill_categories={s: "core" for s in extracted},
        client_problem="Needs a dashboard",
        implicit_needs=["data modeling", "stakeholder communication"],
    )


def _mock_generated_proposal(
    case_study_ids: list[str] | None = None,
) -> GeneratedProposal:
    """Build a mock GeneratedProposal with all 5 required sections."""
    cs_ids = case_study_ids or []
    return GeneratedProposal(
        sections=[
            ProposalSection(
                type=ProposalSectionType.hook,
                content="I noticed you need a dashboard solution.",
                annotation="empathy-led opening",
                case_study_ids=[],
            ),
            ProposalSection(
                type=ProposalSectionType.experience,
                content="I have built 20+ dashboards for similar clients.",
                annotation="social proof",
                case_study_ids=cs_ids,
            ),
            ProposalSection(
                type=ProposalSectionType.approach,
                content="I would start with a discovery call to map your KPIs.",
                annotation="process transparency",
                case_study_ids=[],
            ),
            ProposalSection(
                type=ProposalSectionType.differentiator,
                content="Unlike most freelancers, I deliver DAX documentation.",
                annotation="unique value",
                case_study_ids=[],
            ),
            ProposalSection(
                type=ProposalSectionType.cta,
                content="Shall we schedule a 15-minute call this week?",
                annotation="soft CTA",
                case_study_ids=[],
            ),
        ],
        bid_amount=3500.0,
        estimated_duration="2-3 weeks",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Contract scoring pipeline
# ═══════════════════════════════════════════════════════════════════════════════


class TestContractScoringPipeline:
    """Create a contract, analyse its skills (mock AI), calculate match
    score, calculate ROI score, and verify indicators."""

    @pytest.mark.asyncio
    async def test_scoring_pipeline_end_to_end(self, client, api_session_factory):
        """Full pipeline: create contract -> analyse -> match -> ROI -> indicator."""
        # 1. Seed a contract with known financials
        async with api_session_factory() as session:
            contract = ContractDB(
                platform="upwork",
                external_id="score-pipe-1",
                title="Power BI Executive Dashboard",
                description="Build a KPI dashboard with DAX measures.",
                skills_required=["Power BI", "DAX", "SQL"],
                budget_min=3000.0,
                budget_max=8000.0,
                contract_type=ContractType.fixed,
                duration="2-4 weeks",
                proposals_count=10,
                client_hire_rate=0.85,
                client_total_spent=50000.0,
                connects_cost=8,
                posted_at=datetime(2026, 3, 15),
            )
            session.add(contract)
            await session.commit()
            await session.refresh(contract)
            contract_id = contract.id

        # 2. Mock AI analysis and generate a proposal (which triggers scoring)
        mock_analysis = _mock_analysis(["Power BI", "SQL", "DAX"])
        mock_proposal = _mock_generated_proposal()

        with (
            patch(
                "backend.api.proposals.analyze_contract",
                new_callable=AsyncMock,
                return_value=mock_analysis,
            ),
            patch(
                "backend.api.proposals.generate_proposal",
                new_callable=AsyncMock,
                return_value=mock_proposal,
            ),
        ):
            resp = await client.post(f"/api/contracts/{contract_id}/propose")
            assert resp.status_code == 200

        # 3. Verify the contract now has a match_score set
        resp = await client.get(f"/api/contracts/{contract_id}")
        assert resp.status_code == 200
        contract_data = resp.json()

        assert contract_data["match_score"] is not None
        assert contract_data["match_score"] > 0
        # With 3 core skill hits out of 3 extracted, match_score = 1.0
        assert contract_data["match_score"] == 1.0

        # 4. Verify indicator is present
        assert "indicator" in contract_data
        assert contract_data["indicator"] in ("green", "yellow", "red")

    @pytest.mark.asyncio
    async def test_multiple_contracts_have_correct_indicator_distribution(
        self, client, api_session_factory
    ):
        """Seed multiple contracts with different ROI scores and verify
        indicators are assigned based on percentile ranking."""
        async with api_session_factory() as session:
            contracts = [
                ContractDB(
                    platform="upwork",
                    external_id=f"ind-{i}",
                    title=f"Contract {i}",
                    skills_required=["Python"],
                    budget_max=float(i * 1000),
                    contract_type=ContractType.fixed,
                    roi_score=float(i),
                    match_score=0.8,
                )
                for i in range(1, 9)  # 8 contracts with ROI 1..8
            ]
            session.add_all(contracts)
            await session.commit()

        resp = await client.get("/api/contracts")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 8

        # Sorted by ROI descending
        roi_scores = [c["roi_score"] for c in data]
        assert roi_scores == sorted(roi_scores, reverse=True)

        indicators = [c["indicator"] for c in data]
        # With 8 values (1-8): p25=2.75, p75=6.25
        # Green: > 6.25 -> ROI 7, 8
        # Red: < 2.75 -> ROI 1, 2
        # Yellow: the rest
        assert indicators.count("green") >= 1
        assert indicators.count("red") >= 1
        assert indicators.count("yellow") >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Proposal generation pipeline
# ═══════════════════════════════════════════════════════════════════════════════


class TestProposalGenerationPipeline:
    """Create a contract, seed case studies, generate a proposal (mock AI),
    and verify sections match ProposalSection schema with case study refs."""

    @pytest.mark.asyncio
    async def test_proposal_sections_match_schema(self, client, api_session_factory):
        """Verify generated proposal has exactly 5 sections with correct types."""
        # Seed a contract
        async with api_session_factory() as session:
            c = ContractDB(
                platform="upwork",
                external_id="prop-pipe-1",
                title="Tableau Dashboard for Marketing",
                description="Build a marketing analytics dashboard.",
                skills_required=["Tableau", "SQL"],
                budget_min=2000.0,
                budget_max=5000.0,
                contract_type=ContractType.fixed,
                client_hire_rate=0.8,
                proposals_count=10,
                connects_cost=6,
            )
            session.add(c)
            await session.commit()
            await session.refresh(c)
            contract_id = c.id

        mock_analysis = _mock_analysis(["Tableau", "SQL"])
        mock_proposal = _mock_generated_proposal()

        with (
            patch(
                "backend.api.proposals.analyze_contract",
                new_callable=AsyncMock,
                return_value=mock_analysis,
            ),
            patch(
                "backend.api.proposals.generate_proposal",
                new_callable=AsyncMock,
                return_value=mock_proposal,
            ),
        ):
            resp = await client.post(f"/api/contracts/{contract_id}/propose")

        assert resp.status_code == 200
        data = resp.json()

        # Verify exactly 5 sections
        sections = data["sections"]
        assert len(sections) == 5

        # Verify section types match ProposalSectionType enum
        expected_types = {"hook", "experience", "approach", "differentiator", "cta"}
        actual_types = {s["type"] for s in sections}
        assert actual_types == expected_types

        # Verify each section has content
        for section in sections:
            assert "content" in section
            assert isinstance(section["content"], str)
            assert len(section["content"]) > 0
            # annotation is optional but should be present in our mock
            assert "annotation" in section

    @pytest.mark.asyncio
    async def test_proposal_includes_case_study_references(
        self, client, api_session_factory
    ):
        """Verify case study slugs are passed through to the proposal."""
        # Seed a contract
        async with api_session_factory() as session:
            c = ContractDB(
                platform="upwork",
                external_id="prop-cs-1",
                title="Power BI Dashboard Project",
                description="Dashboard work.",
                skills_required=["Power BI"],
                budget_max=5000.0,
                contract_type=ContractType.fixed,
                client_hire_rate=0.85,
                proposals_count=5,
                connects_cost=6,
            )
            session.add(c)
            await session.commit()
            await session.refresh(c)
            contract_id = c.id

        mock_analysis = _mock_analysis(["Power BI"])
        mock_proposal = _mock_generated_proposal(
            case_study_ids=["fintech-dashboard"]
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
                return_value=mock_proposal,
            ),
        ):
            resp = await client.post(f"/api/contracts/{contract_id}/propose")

        assert resp.status_code == 200
        data = resp.json()

        # matched_case_studies should contain the slug from the experience section
        assert "fintech-dashboard" in data["matched_case_studies"]

    @pytest.mark.asyncio
    async def test_proposal_contract_status_updated_to_drafting(
        self, client, api_session_factory
    ):
        """Generating a proposal should update the contract status to drafting."""
        async with api_session_factory() as session:
            c = ContractDB(
                platform="upwork",
                external_id="prop-status-1",
                title="ETL Pipeline",
                description="Build ETL.",
                skills_required=["Python", "ETL"],
                budget_max=4000.0,
                contract_type=ContractType.fixed,
                client_hire_rate=0.8,
                proposals_count=10,
                connects_cost=6,
            )
            session.add(c)
            await session.commit()
            await session.refresh(c)
            contract_id = c.id

        mock_analysis = _mock_analysis(["Python", "ETL"])
        mock_proposal = _mock_generated_proposal()

        with (
            patch(
                "backend.api.proposals.analyze_contract",
                new_callable=AsyncMock,
                return_value=mock_analysis,
            ),
            patch(
                "backend.api.proposals.generate_proposal",
                new_callable=AsyncMock,
                return_value=mock_proposal,
            ),
        ):
            resp = await client.post(f"/api/contracts/{contract_id}/propose")
            assert resp.status_code == 200

        # Verify contract status updated
        resp = await client.get(f"/api/contracts/{contract_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "drafting"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. API round-trip
# ═══════════════════════════════════════════════════════════════════════════════


class TestAPIRoundTrip:
    """POST contracts -> GET /api/contracts with filters -> verify sorted
    by ROI with indicators -> GET single contract -> POST propose -> GET proposal."""

    @pytest.mark.asyncio
    async def test_full_round_trip(self, client, api_session_factory):
        """End-to-end: seed -> list -> filter -> get -> propose -> get proposal."""
        # 1. Seed multiple contracts directly in DB
        async with api_session_factory() as session:
            contracts = [
                ContractDB(
                    platform="upwork",
                    external_id="rt-1",
                    title="Power BI Dashboard",
                    skills_required=["Power BI", "SQL"],
                    budget_min=2000.0,
                    budget_max=5000.0,
                    contract_type=ContractType.fixed,
                    roi_score=15.0,
                    match_score=0.9,
                    client_hire_rate=0.85,
                    proposals_count=8,
                    connects_cost=6,
                ),
                ContractDB(
                    platform="upwork",
                    external_id="rt-2",
                    title="Python Automation Script",
                    skills_required=["Python", "Automation"],
                    budget_min=300.0,
                    budget_max=800.0,
                    contract_type=ContractType.fixed,
                    roi_score=3.0,
                    match_score=0.5,
                    client_hire_rate=0.6,
                    proposals_count=25,
                    connects_cost=4,
                ),
                ContractDB(
                    platform="upwork",
                    external_id="rt-3",
                    title="Tableau Visualization",
                    skills_required=["Tableau", "SQL", "Data modeling"],
                    budget_min=4000.0,
                    budget_max=10000.0,
                    contract_type=ContractType.fixed,
                    roi_score=22.0,
                    match_score=0.85,
                    client_hire_rate=0.9,
                    proposals_count=12,
                    connects_cost=10,
                ),
                ContractDB(
                    platform="upwork",
                    external_id="rt-4",
                    title="Hourly BI Consultant",
                    skills_required=["Power BI", "DAX"],
                    budget_min=80.0,
                    budget_max=120.0,
                    contract_type=ContractType.hourly,
                    roi_score=30.0,
                    match_score=0.95,
                    client_hire_rate=0.92,
                    proposals_count=3,
                    connects_cost=8,
                ),
            ]
            session.add_all(contracts)
            await session.commit()

        # 2. GET /api/contracts — verify sorted by ROI descending
        resp = await client.get("/api/contracts")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 4
        roi_scores = [c["roi_score"] for c in data]
        assert roi_scores == sorted(roi_scores, reverse=True)

        # Verify all have indicators
        for c in data:
            assert "indicator" in c
            assert c["indicator"] in ("green", "yellow", "red")

        # 3. Filter by contract_type=fixed
        resp = await client.get("/api/contracts", params={"contract_type": "fixed"})
        assert resp.status_code == 200
        fixed_data = resp.json()
        assert len(fixed_data) == 3
        assert all(c["contract_type"] == "fixed" for c in fixed_data)

        # 4. Filter by skill
        resp = await client.get("/api/contracts", params={"skill": "Power BI"})
        assert resp.status_code == 200
        pbi_data = resp.json()
        assert len(pbi_data) == 2  # rt-1 and rt-4

        # 5. Filter by min_roi
        resp = await client.get("/api/contracts", params={"min_roi": 20.0})
        assert resp.status_code == 200
        high_roi = resp.json()
        assert len(high_roi) == 2  # rt-3 (22.0) and rt-4 (30.0)
        assert all(c["roi_score"] >= 20.0 for c in high_roi)

        # 6. GET single contract
        contract_id = data[0]["id"]  # highest ROI
        resp = await client.get(f"/api/contracts/{contract_id}")
        assert resp.status_code == 200
        single = resp.json()
        assert single["id"] == contract_id
        assert "indicator" in single

        # 7. POST propose (with mocked AI)
        mock_analysis = _mock_analysis(["Power BI", "DAX"])
        mock_proposal = _mock_generated_proposal()

        with (
            patch(
                "backend.api.proposals.analyze_contract",
                new_callable=AsyncMock,
                return_value=mock_analysis,
            ),
            patch(
                "backend.api.proposals.generate_proposal",
                new_callable=AsyncMock,
                return_value=mock_proposal,
            ),
        ):
            resp = await client.post(f"/api/contracts/{contract_id}/propose")
        assert resp.status_code == 200
        proposal = resp.json()
        assert proposal["contract_id"] == contract_id
        proposal_id = proposal["id"]

        # 8. GET proposal
        resp = await client.get(f"/api/proposals/{proposal_id}")
        assert resp.status_code == 200
        fetched_proposal = resp.json()
        assert fetched_proposal["id"] == proposal_id
        assert fetched_proposal["bid_amount"] == 3500.0
        assert len(fetched_proposal["sections"]) == 5

    @pytest.mark.asyncio
    async def test_filter_by_budget_range(self, client, api_session_factory):
        """Verify budget_min and budget_max filters work correctly."""
        async with api_session_factory() as session:
            contracts = [
                ContractDB(
                    platform="upwork",
                    external_id="bud-1",
                    title="Small Job",
                    budget_min=100.0,
                    budget_max=500.0,
                    contract_type=ContractType.fixed,
                    roi_score=2.0,
                ),
                ContractDB(
                    platform="upwork",
                    external_id="bud-2",
                    title="Medium Job",
                    budget_min=1000.0,
                    budget_max=3000.0,
                    contract_type=ContractType.fixed,
                    roi_score=8.0,
                ),
                ContractDB(
                    platform="upwork",
                    external_id="bud-3",
                    title="Large Job",
                    budget_min=5000.0,
                    budget_max=15000.0,
                    contract_type=ContractType.fixed,
                    roi_score=20.0,
                ),
            ]
            session.add_all(contracts)
            await session.commit()

        # Filter budget_min >= 1000
        resp = await client.get("/api/contracts", params={"budget_min": 1000})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert all(c["budget_min"] >= 1000 for c in data)

        # Filter budget_max <= 3000
        resp = await client.get("/api/contracts", params={"budget_max": 3000})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert all(c["budget_max"] <= 3000 for c in data)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Availability filtering
# ═══════════════════════════════════════════════════════════════════════════════


class TestAvailabilityFiltering:
    """Set availability via PUT, then verify contracts are filtered correctly
    based on rate floors and contract type preferences."""

    @pytest.mark.asyncio
    async def test_availability_rate_floor_filtering(self, client, api_session_factory):
        """Set min_hourly_rate via PUT, then verify filtering logic."""
        # 1. Set availability with a $100/hr floor
        avail_update = {
            "hours_per_week": 40,
            "max_concurrent_contracts": 3,
            "current_committed_hours": 0,
            "preferred_duration": "any",
            "preferred_contract_type": "both",
            "min_hourly_rate": 100.0,
            "min_fixed_budget": 2000.0,
            "hourly_value": 100.0,
        }
        resp = await client.put("/api/availability", json=avail_update)
        assert resp.status_code == 200
        avail = resp.json()
        assert avail["min_hourly_rate"] == 100.0
        assert avail["min_fixed_budget"] == 2000.0

        # 2. Read it back
        resp = await client.get("/api/availability")
        assert resp.status_code == 200
        assert resp.json()["min_hourly_rate"] == 100.0

        # 3. Seed contracts at, below, and above the rate floor
        async with api_session_factory() as session:
            contracts = [
                # Below hourly floor ($75 < $100)
                ContractDB(
                    platform="upwork",
                    external_id="avail-below",
                    title="Cheap Hourly",
                    budget_min=50.0,
                    budget_max=75.0,
                    contract_type=ContractType.hourly,
                    roi_score=5.0,
                ),
                # At hourly floor ($100 == $100)
                ContractDB(
                    platform="upwork",
                    external_id="avail-at",
                    title="At Rate Hourly",
                    budget_min=80.0,
                    budget_max=100.0,
                    contract_type=ContractType.hourly,
                    roi_score=10.0,
                ),
                # Above hourly floor ($150 > $100)
                ContractDB(
                    platform="upwork",
                    external_id="avail-above",
                    title="Premium Hourly",
                    budget_min=120.0,
                    budget_max=150.0,
                    contract_type=ContractType.hourly,
                    roi_score=20.0,
                ),
                # Fixed contract below budget floor ($1000 < $2000)
                ContractDB(
                    platform="upwork",
                    external_id="avail-fixed-below",
                    title="Small Fixed",
                    budget_min=500.0,
                    budget_max=1000.0,
                    contract_type=ContractType.fixed,
                    roi_score=3.0,
                ),
                # Fixed contract above budget floor ($5000 > $2000)
                ContractDB(
                    platform="upwork",
                    external_id="avail-fixed-above",
                    title="Large Fixed",
                    budget_min=3000.0,
                    budget_max=5000.0,
                    contract_type=ContractType.fixed,
                    roi_score=15.0,
                ),
            ]
            session.add_all(contracts)
            await session.commit()

        # 4. Verify all contracts exist in DB
        resp = await client.get("/api/contracts")
        assert resp.status_code == 200
        all_contracts = resp.json()
        assert len(all_contracts) == 5

        # 5. Now verify the availability filter logic directly
        #    (The API doesn't filter by availability automatically on GET;
        #    the filter is used during scanning. We test the scoring module.)
        from backend.core.models import AvailabilityConfig, Contract
        from backend.core.scoring import passes_availability_filter

        avail_config = AvailabilityConfig(**avail_update)

        for c_data in all_contracts:
            contract = Contract(**c_data)
            passes = passes_availability_filter(contract, avail_config)

            if c_data["external_id"] == "avail-below":
                assert not passes, "Below hourly floor should fail"
            elif c_data["external_id"] == "avail-at":
                assert passes, "At hourly floor should pass"
            elif c_data["external_id"] == "avail-above":
                assert passes, "Above hourly floor should pass"
            elif c_data["external_id"] == "avail-fixed-below":
                assert not passes, "Below fixed budget floor should fail"
            elif c_data["external_id"] == "avail-fixed-above":
                assert passes, "Above fixed budget floor should pass"

    @pytest.mark.asyncio
    async def test_availability_contract_type_preference(self, client, api_session_factory):
        """Set preferred_contract_type to hourly and verify fixed contracts are filtered."""
        # Set preference to hourly only
        avail_update = {
            "hours_per_week": 40,
            "max_concurrent_contracts": 3,
            "current_committed_hours": 0,
            "preferred_duration": "any",
            "preferred_contract_type": "hourly",
            "min_hourly_rate": 50.0,
            "min_fixed_budget": 500.0,
            "hourly_value": 100.0,
        }
        resp = await client.put("/api/availability", json=avail_update)
        assert resp.status_code == 200

        # Seed contracts of both types
        async with api_session_factory() as session:
            contracts = [
                ContractDB(
                    platform="upwork",
                    external_id="pref-hourly",
                    title="Hourly Job",
                    budget_max=100.0,
                    contract_type=ContractType.hourly,
                    roi_score=10.0,
                ),
                ContractDB(
                    platform="upwork",
                    external_id="pref-fixed",
                    title="Fixed Job",
                    budget_max=5000.0,
                    contract_type=ContractType.fixed,
                    roi_score=8.0,
                ),
            ]
            session.add_all(contracts)
            await session.commit()

        # Verify filter
        from backend.core.models import AvailabilityConfig, Contract
        from backend.core.scoring import passes_availability_filter

        avail_config = AvailabilityConfig(**avail_update)

        resp = await client.get("/api/contracts")
        all_contracts = resp.json()

        for c_data in all_contracts:
            contract = Contract(**c_data)
            passes = passes_availability_filter(contract, avail_config)
            if c_data["external_id"] == "pref-hourly":
                assert passes, "Hourly job should pass hourly preference"
            elif c_data["external_id"] == "pref-fixed":
                assert not passes, "Fixed job should fail hourly preference"


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Proposal versioning
# ═══════════════════════════════════════════════════════════════════════════════


class TestProposalVersioning:
    """Verify that generating multiple proposals for the same contract
    increments the version number."""

    @pytest.mark.asyncio
    async def test_proposal_version_increments(self, client, api_session_factory):
        """Generating a second proposal should have version=2."""
        async with api_session_factory() as session:
            c = ContractDB(
                platform="upwork",
                external_id="ver-1",
                title="Dashboard Project",
                skills_required=["Power BI"],
                budget_max=5000.0,
                contract_type=ContractType.fixed,
                client_hire_rate=0.8,
                proposals_count=10,
                connects_cost=6,
            )
            session.add(c)
            await session.commit()
            await session.refresh(c)
            contract_id = c.id

        mock_analysis = _mock_analysis(["Power BI"])
        mock_proposal = _mock_generated_proposal()

        for expected_version in (1, 2):
            with (
                patch(
                    "backend.api.proposals.analyze_contract",
                    new_callable=AsyncMock,
                    return_value=mock_analysis,
                ),
                patch(
                    "backend.api.proposals.generate_proposal",
                    new_callable=AsyncMock,
                    return_value=mock_proposal,
                ),
            ):
                resp = await client.post(f"/api/contracts/{contract_id}/propose")
            assert resp.status_code == 200
            assert resp.json()["version"] == expected_version


# ═══════════════════════════════════════════════════════════════════════════════
# 6. History tracking integration
# ═══════════════════════════════════════════════════════════════════════════════


class TestHistoryIntegration:
    """Verify the full history flow: create proposal -> record application -> view stats."""

    @pytest.mark.asyncio
    async def test_proposal_to_history_flow(self, client, api_session_factory):
        """Generate proposal -> record in history -> verify stats."""
        # Seed contract
        async with api_session_factory() as session:
            c = ContractDB(
                platform="upwork",
                external_id="hist-1",
                title="AI Chatbot",
                skills_required=["Python", "LangChain"],
                budget_max=10000.0,
                contract_type=ContractType.fixed,
                client_hire_rate=0.7,
                proposals_count=20,
                connects_cost=12,
            )
            session.add(c)
            await session.commit()
            await session.refresh(c)
            contract_id = c.id

        # Generate proposal
        mock_analysis = _mock_analysis(["Python", "LangChain"])
        mock_proposal = _mock_generated_proposal()

        with (
            patch(
                "backend.api.proposals.analyze_contract",
                new_callable=AsyncMock,
                return_value=mock_analysis,
            ),
            patch(
                "backend.api.proposals.generate_proposal",
                new_callable=AsyncMock,
                return_value=mock_proposal,
            ),
        ):
            resp = await client.post(f"/api/contracts/{contract_id}/propose")
        assert resp.status_code == 200
        proposal_id = resp.json()["id"]

        # Record application in history
        resp = await client.post(
            "/api/history",
            json={
                "contract_id": contract_id,
                "proposal_id": proposal_id,
                "connects_spent": 12,
            },
        )
        assert resp.status_code == 201
        history = resp.json()
        assert history["contract_id"] == contract_id
        assert history["proposal_id"] == proposal_id
        assert history["connects_spent"] == 12
        assert history["outcome"] == "submitted"

        # Verify stats
        resp = await client.get("/api/history/stats")
        assert resp.status_code == 200
        stats = resp.json()
        assert stats["total_applications"] == 1
        assert stats["connects_spent"] == 12
        assert stats["outcomes_breakdown"]["submitted"] == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Health check
# ═══════════════════════════════════════════════════════════════════════════════


class TestHealthCheck:
    """Basic smoke test for the health endpoint."""

    @pytest.mark.asyncio
    async def test_health_endpoint(self, client):
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "contract-finder-api"
