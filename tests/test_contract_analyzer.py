"""Tests for the AI contract analyzer (backend.ai.contract_analyzer)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from backend.ai.contract_analyzer import ContractAnalysis, analyze_contract, _categorize_skills


# ── Helpers ──────────────────────────────────────────────────────────────────


def _mock_claude_response(text: str) -> AsyncMock:
    """Build a mock Anthropic client whose messages.create returns the given text."""
    content_block = SimpleNamespace(text=text)
    response = SimpleNamespace(content=[content_block])

    client = AsyncMock()
    client.messages.create = AsyncMock(return_value=response)
    return client


# ── _categorize_skills unit tests ────────────────────────────────────────────


def test_categorize_skills_core():
    result = _categorize_skills(["Python", "FastAPI"], ["python", "fastapi"], [])
    assert result == {"Python": "core", "FastAPI": "core"}


def test_categorize_skills_adjacent():
    result = _categorize_skills(["Docker"], [], ["docker"])
    assert result == {"Docker": "adjacent"}


def test_categorize_skills_unmatched():
    result = _categorize_skills(["Rust"], ["Python"], ["Docker"])
    assert result == {"Rust": "unmatched"}


def test_categorize_skills_mixed():
    result = _categorize_skills(
        ["Python", "Docker", "Rust"],
        ["python"],
        ["docker"],
    )
    assert result == {"Python": "core", "Docker": "adjacent", "Rust": "unmatched"}


# ── Valid JSON response ──────────────────────────────────────────────────────


async def test_analyze_contract_valid_json():
    """Mock Claude returning valid JSON -> verify extracted_skills, skill_categories, client_problem."""
    claude_response = json.dumps({
        "extracted_skills": ["Python", "FastAPI", "PostgreSQL", "Docker"],
        "client_problem": "The client needs a scalable REST API for their e-commerce platform.",
        "implicit_needs": ["API documentation", "Database migrations", "Error handling", "Testing"],
    })

    client = _mock_claude_response(claude_response)

    result = await analyze_contract(
        title="Build REST API for E-commerce Platform",
        description="We need an experienced Python developer to build a REST API...",
        skills_tags=["Python", "FastAPI", "PostgreSQL"],
        core_skills=["Python", "FastAPI"],
        adjacent_skills=["PostgreSQL"],
        client=client,
    )

    assert isinstance(result, ContractAnalysis)
    assert result.extracted_skills == ["Python", "FastAPI", "PostgreSQL", "Docker"]
    assert result.skill_categories["Python"] == "core"
    assert result.skill_categories["FastAPI"] == "core"
    assert result.skill_categories["PostgreSQL"] == "adjacent"
    assert result.skill_categories["Docker"] == "unmatched"
    assert "scalable REST API" in result.client_problem
    assert len(result.implicit_needs) == 4
    assert "API documentation" in result.implicit_needs


async def test_analyze_contract_no_profile_skills():
    """When no profile skills are provided, all extracted skills are unmatched."""
    claude_response = json.dumps({
        "extracted_skills": ["React", "TypeScript"],
        "client_problem": "Need a frontend developer.",
        "implicit_needs": ["Responsive design"],
    })

    client = _mock_claude_response(claude_response)

    result = await analyze_contract(
        title="Frontend Developer",
        description="Build a React dashboard.",
        skills_tags=["React"],
        client=client,
    )

    assert result.skill_categories["React"] == "unmatched"
    assert result.skill_categories["TypeScript"] == "unmatched"


# ── Malformed JSON response ─────────────────────────────────────────────────


async def test_analyze_contract_malformed_json():
    """Mock Claude returning malformed JSON -> verify graceful error handling."""
    client = _mock_claude_response("This is not valid JSON at all {broken")

    with pytest.raises(ValueError, match="Claude returned invalid JSON"):
        await analyze_contract(
            title="Test Contract",
            description="Some description",
            skills_tags=["Python"],
            client=client,
        )


async def test_analyze_contract_invalid_skills_type():
    """If extracted_skills is not a list, raise ValueError."""
    claude_response = json.dumps({
        "extracted_skills": "Python",  # should be a list
        "client_problem": "Something",
        "implicit_needs": [],
    })

    client = _mock_claude_response(claude_response)

    with pytest.raises(ValueError, match="extracted_skills must be a list"):
        await analyze_contract(
            title="Test",
            description="Desc",
            skills_tags=[],
            client=client,
        )


async def test_analyze_contract_invalid_client_problem_type():
    """If client_problem is not a string, raise ValueError."""
    claude_response = json.dumps({
        "extracted_skills": ["Python"],
        "client_problem": 42,  # should be a string
        "implicit_needs": [],
    })

    client = _mock_claude_response(claude_response)

    with pytest.raises(ValueError, match="client_problem must be a string"):
        await analyze_contract(
            title="Test",
            description="Desc",
            skills_tags=[],
            client=client,
        )


async def test_analyze_contract_invalid_implicit_needs_type():
    """If implicit_needs is not a list, raise ValueError."""
    claude_response = json.dumps({
        "extracted_skills": ["Python"],
        "client_problem": "Problem",
        "implicit_needs": "not a list",
    })

    client = _mock_claude_response(claude_response)

    with pytest.raises(ValueError, match="implicit_needs must be a list"):
        await analyze_contract(
            title="Test",
            description="Desc",
            skills_tags=[],
            client=client,
        )


# ── Prompt content verification ─────────────────────────────────────────────


async def test_system_prompt_includes_contract_details():
    """Verify the system prompt includes the contract title and description."""
    claude_response = json.dumps({
        "extracted_skills": ["Python"],
        "client_problem": "Need help.",
        "implicit_needs": [],
    })

    client = _mock_claude_response(claude_response)

    await analyze_contract(
        title="My Specific Contract Title",
        description="This is a very unique contract description for testing.",
        skills_tags=["SpecialSkill"],
        client=client,
    )

    # Verify the call was made and the prompt contains contract details
    call_args = client.messages.create.call_args
    messages = call_args.kwargs["messages"]
    user_content = messages[0]["content"]

    assert "My Specific Contract Title" in user_content
    assert "This is a very unique contract description for testing." in user_content
    assert "SpecialSkill" in user_content


async def test_analyze_contract_empty_skills_tags():
    """When skills_tags is empty, the prompt shows 'None listed'."""
    claude_response = json.dumps({
        "extracted_skills": [],
        "client_problem": "Vague request.",
        "implicit_needs": [],
    })

    client = _mock_claude_response(claude_response)

    await analyze_contract(
        title="Vague Project",
        description="Do something.",
        skills_tags=[],
        client=client,
    )

    call_args = client.messages.create.call_args
    messages = call_args.kwargs["messages"]
    user_content = messages[0]["content"]

    assert "None listed" in user_content
