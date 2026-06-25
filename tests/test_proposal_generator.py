"""Tests for the AI proposal generator (backend.ai.proposal_generator)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.ai.proposal_generator import (
    GeneratedProposal,
    generate_proposal,
    _format_budget_range,
    _validate_case_study_ids,
)
from backend.core.enums import ContractType, ProposalSectionType
from backend.core.models import (
    AvailabilityConfig,
    Contract,
    LoadedProfile,
    ProposalSection,
    SkillProfile,
    WeightedSkill,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _mock_claude_response(text: str) -> AsyncMock:
    """Build a mock Anthropic client whose messages.create returns the given text."""
    content_block = SimpleNamespace(text=text)
    response = SimpleNamespace(content=[content_block])

    client = AsyncMock()
    client.messages.create = AsyncMock(return_value=response)
    return client


def _sample_contract() -> Contract:
    return Contract(
        id=1,
        platform="upwork",
        external_id="abc123",
        title="Build a FastAPI Backend",
        description="We need a Python developer to build a FastAPI backend for our SaaS product.",
        skills_required=["Python", "FastAPI", "PostgreSQL"],
        budget_min=2000.0,
        budget_max=5000.0,
        contract_type=ContractType.fixed,
        duration="1-3 months",
    )


def _sample_profile() -> LoadedProfile:
    return LoadedProfile(
        name="Pat",
        studio="Sample Studio",
        positioning="Full-stack developer specializing in Python and React",
        hourly_rate_range=[100.0, 150.0],
        tone="professional",
        selling_points=["Fast delivery", "Clean code", "Great communication"],
        key_differentiators={
            "backend": SkillProfile(
                description="Expert backend development",
                skills=["Python", "FastAPI", "Django"],
            ),
        },
        core_skills=[WeightedSkill(name="Python", weight=1.0), WeightedSkill(name="FastAPI", weight=1.0)],
        adjacent_skills=[WeightedSkill(name="PostgreSQL", weight=0.6)],
        all_skills=[
            WeightedSkill(name="Python", weight=1.0),
            WeightedSkill(name="FastAPI", weight=1.0),
            WeightedSkill(name="PostgreSQL", weight=0.6),
        ],
    )


def _sample_availability() -> AvailabilityConfig:
    return AvailabilityConfig(
        hours_per_week=30,
        min_hourly_rate=100.0,
        min_fixed_budget=1000.0,
    )


def _valid_proposal_json() -> str:
    """Return a valid Claude response with all 5 sections."""
    return json.dumps({
        "sections": [
            {
                "type": "hook",
                "content": "I understand you need a robust FastAPI backend for your SaaS product.",
                "annotation": "Opening with problem acknowledgment to show understanding.",
                "case_study_ids": [],
            },
            {
                "type": "experience",
                "content": "I recently built a high-performance API that achieved 50% faster response times and 99.9% uptime.",
                "annotation": "Referencing ecommerce-api case study with quantified outcomes.",
                "case_study_ids": ["ecommerce-api"],
            },
            {
                "type": "approach",
                "content": "1. Requirements review and API design\n2. Core endpoint implementation\n3. Testing and optimization\n4. Deployment and documentation",
                "annotation": "Structured approach showing methodical process.",
                "case_study_ids": [],
            },
            {
                "type": "differentiator",
                "content": "As a specialist in Python and FastAPI with a track record of delivering clean, well-tested code, I bring both speed and quality.",
                "annotation": "Highlighting core skills that match the contract requirements.",
                "case_study_ids": [],
            },
            {
                "type": "cta",
                "content": "I'd love to schedule a 15-minute call to discuss your architecture needs. Are you available this week?",
                "annotation": "Low-commitment next step to start the conversation.",
                "case_study_ids": [],
            },
        ],
        "bid_amount": 3500.0,
        "estimated_duration": "4-6 weeks",
    })


# ── Helper unit tests ───────────────────────────────────────────────────────


def test_format_budget_range_both():
    contract = _sample_contract()
    assert _format_budget_range(contract) == "$2000-$5000"


def test_format_budget_range_min_only():
    contract = _sample_contract()
    contract.budget_max = None
    assert _format_budget_range(contract) == "$2000+"


def test_format_budget_range_max_only():
    contract = _sample_contract()
    contract.budget_min = None
    assert _format_budget_range(contract) == "Up to $5000"


def test_format_budget_range_none():
    contract = _sample_contract()
    contract.budget_min = None
    contract.budget_max = None
    assert _format_budget_range(contract) == "Not specified"


def test_validate_case_study_ids_filters_invalid():
    sections = [
        {"type": "experience", "case_study_ids": ["valid-slug", "fake-slug"]},
        {"type": "hook", "case_study_ids": []},
    ]
    result = _validate_case_study_ids(sections, {"valid-slug"})
    assert result[0]["case_study_ids"] == ["valid-slug"]
    assert result[1]["case_study_ids"] == []


# ── Valid JSON response ──────────────────────────────────────────────────────


async def test_generate_proposal_valid_json():
    """Mock Claude returning valid JSON with all 5 sections -> verify structure."""
    client = _mock_claude_response(_valid_proposal_json())

    result = await generate_proposal(
        contract=_sample_contract(),
        profile=_sample_profile(),
        availability=_sample_availability(),
        client=client,
    )

    assert isinstance(result, GeneratedProposal)
    assert len(result.sections) == 5

    # Check all section types present
    section_types = {s.type for s in result.sections}
    assert section_types == {
        ProposalSectionType.hook,
        ProposalSectionType.experience,
        ProposalSectionType.approach,
        ProposalSectionType.differentiator,
        ProposalSectionType.cta,
    }

    # Check each section has content and annotation
    for section in result.sections:
        assert isinstance(section, ProposalSection)
        assert section.content
        assert section.annotation

    # Check bid_amount and estimated_duration
    assert result.bid_amount == 3500.0
    assert result.estimated_duration == "4-6 weeks"


async def test_proposal_case_study_ids_reference_real_slugs():
    """Verify case_study_ids reference actual case study slugs."""
    client = _mock_claude_response(_valid_proposal_json())

    result = await generate_proposal(
        contract=_sample_contract(),
        profile=_sample_profile(),
        availability=_sample_availability(),
        client=client,
    )

    valid_slugs = {"ecommerce-api", "dashboard-app"}
    for section in result.sections:
        if section.case_study_ids:
            for slug in section.case_study_ids:
                assert slug in valid_slugs, f"Invalid case study slug: {slug}"


async def test_proposal_filters_invalid_case_study_ids():
    """If Claude returns invalid case study slugs, they are filtered out.

    With detailed_case_studies=None the generator loads the file-based studies
    from the fixture profile (sample-analytics.md), so only the real slug
    survives and a fabricated one is dropped.
    """
    response_data = json.loads(_valid_proposal_json())
    # Mix the real fixture slug with a fabricated one in the experience section.
    response_data["sections"][1]["case_study_ids"] = ["sample-analytics", "nonexistent-project"]
    client = _mock_claude_response(json.dumps(response_data))

    result = await generate_proposal(
        contract=_sample_contract(),
        profile=_sample_profile(),
        availability=_sample_availability(),
        client=client,
        detailed_case_studies=None,  # Loads the fixture study from disk
    )

    # The experience section should only retain the real slug.
    experience = [s for s in result.sections if s.type == ProposalSectionType.experience][0]
    assert experience.case_study_ids == ["sample-analytics"]


# ── Malformed JSON response ─────────────────────────────────────────────────


async def test_generate_proposal_malformed_json():
    """Mock Claude returning malformed JSON -> verify graceful error handling."""
    client = _mock_claude_response("This is not valid JSON {broken")

    with pytest.raises(ValueError, match="Claude returned invalid JSON"):
        await generate_proposal(
            contract=_sample_contract(),
            profile=_sample_profile(),
            availability=_sample_availability(),
            client=client,
        )


async def test_generate_proposal_wrong_section_count():
    """If Claude returns != 5 sections, raise ValueError."""
    response_data = json.loads(_valid_proposal_json())
    response_data["sections"] = response_data["sections"][:3]  # only 3 sections
    client = _mock_claude_response(json.dumps(response_data))

    with pytest.raises(ValueError, match="exactly 5 sections"):
        await generate_proposal(
            contract=_sample_contract(),
            profile=_sample_profile(),
            availability=_sample_availability(),
            client=client,
        )


async def test_generate_proposal_invalid_section_type():
    """If Claude returns an invalid section type, raise ValueError."""
    response_data = json.loads(_valid_proposal_json())
    response_data["sections"][0]["type"] = "invalid_type"
    client = _mock_claude_response(json.dumps(response_data))

    with pytest.raises(ValueError, match="Invalid section type"):
        await generate_proposal(
            contract=_sample_contract(),
            profile=_sample_profile(),
            availability=_sample_availability(),
            client=client,
        )


async def test_generate_proposal_missing_bid_amount():
    """If bid_amount is missing or not a number, raise ValueError."""
    response_data = json.loads(_valid_proposal_json())
    response_data["bid_amount"] = "not a number"
    client = _mock_claude_response(json.dumps(response_data))

    with pytest.raises(ValueError, match="bid_amount must be a number"):
        await generate_proposal(
            contract=_sample_contract(),
            profile=_sample_profile(),
            availability=_sample_availability(),
            client=client,
        )


async def test_generate_proposal_missing_estimated_duration():
    """If estimated_duration is not a string, raise ValueError."""
    response_data = json.loads(_valid_proposal_json())
    response_data["estimated_duration"] = 42
    client = _mock_claude_response(json.dumps(response_data))

    with pytest.raises(ValueError, match="estimated_duration must be a string"):
        await generate_proposal(
            contract=_sample_contract(),
            profile=_sample_profile(),
            availability=_sample_availability(),
            client=client,
        )


# ── Bid amount and estimated duration ────────────────────────────────────────


async def test_bid_amount_and_duration_present():
    """Verify bid_amount and estimated_duration are present in the result."""
    client = _mock_claude_response(_valid_proposal_json())

    result = await generate_proposal(
        contract=_sample_contract(),
        profile=_sample_profile(),
        availability=_sample_availability(),
        client=client,
    )

    assert isinstance(result.bid_amount, float)
    assert result.bid_amount > 0
    assert isinstance(result.estimated_duration, str)
    assert len(result.estimated_duration) > 0
