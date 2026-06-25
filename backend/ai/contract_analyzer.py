"""AI-powered contract analysis — extracts skills, client problem, and implicit needs."""

from __future__ import annotations

import functools
import json
import logging
from pathlib import Path

import anthropic
from pydantic import BaseModel

from backend.ai.usage import record_usage
from backend.config import settings

logger = logging.getLogger(__name__)

# ── Prompt template ─────────────────────────────────────────────────────────

_PROMPT_PATH = Path(__file__).parent / "prompts" / "contract_analysis.txt"


@functools.lru_cache(maxsize=1)
def _load_prompt() -> str:
    """Load the contract analysis prompt template (cached after first read)."""
    return _PROMPT_PATH.read_text(encoding="utf-8")


# ── Result model ────────────────────────────────────────────────────────────


class ContractAnalysis(BaseModel):
    """Structured result of AI contract analysis."""

    extracted_skills: list[str]
    skill_categories: dict[str, str]  # skill -> "core" | "adjacent" | "unmatched"
    client_problem: str
    implicit_needs: list[str]
    description_fit_score: float = 0.0


# ── Public API ──────────────────────────────────────────────────────────────


def _categorize_skills(
    extracted_skills: list[str],
    core_skills: list[str],
    adjacent_skills: list[str],
) -> dict[str, str]:
    """Categorize each extracted skill as core, adjacent, or unmatched.

    Comparison is case-insensitive.
    """
    core_lower = {s.lower() for s in core_skills}
    adjacent_lower = {s.lower() for s in adjacent_skills}

    categories: dict[str, str] = {}
    for skill in extracted_skills:
        skill_lower = skill.lower()
        if skill_lower in core_lower:
            categories[skill] = "core"
        elif skill_lower in adjacent_lower:
            categories[skill] = "adjacent"
        else:
            categories[skill] = "unmatched"
    return categories


async def analyze_contract(
    title: str,
    description: str,
    skills_tags: list[str],
    core_skills: list[str] | None = None,
    adjacent_skills: list[str] | None = None,
    client: anthropic.AsyncAnthropic | None = None,
) -> ContractAnalysis:
    """Analyze a contract listing using Claude to extract structured information.

    Parameters
    ----------
    title:
        The contract title.
    description:
        The full contract description text.
    skills_tags:
        Skill tags listed on the contract.
    core_skills:
        The freelancer's core skills (for categorization). Defaults to empty.
    adjacent_skills:
        The freelancer's adjacent skills (for categorization). Defaults to empty.
    client:
        Optional pre-configured AsyncAnthropic client (useful for testing).

    Returns
    -------
    ContractAnalysis
        Structured analysis with extracted skills, categories, problem summary,
        and implicit needs.

    Raises
    ------
    ValueError
        If Claude's response cannot be parsed as valid JSON.
    """
    if core_skills is None:
        core_skills = []
    if adjacent_skills is None:
        adjacent_skills = []

    prompt_template = _load_prompt()
    user_message = prompt_template.format(
        title=title,
        description=description,
        skills_tags=", ".join(skills_tags) if skills_tags else "None listed",
    )

    if client is None:
        client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    response = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": user_message}],
    )
    record_usage("claude-sonnet-4-6", response)

    # Extract text from Claude's response
    if not response.content:
        raise ValueError("Claude returned an empty response")
    raw_text = response.content[0].text

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse Claude response as JSON: %s", raw_text[:500])
        raise ValueError(f"Claude returned invalid JSON: {exc}") from exc

    extracted_skills = data.get("extracted_skills", [])
    if not isinstance(extracted_skills, list):
        raise ValueError("extracted_skills must be a list")

    client_problem = data.get("client_problem", "")
    if not isinstance(client_problem, str):
        raise ValueError("client_problem must be a string")

    implicit_needs = data.get("implicit_needs", [])
    if not isinstance(implicit_needs, list):
        raise ValueError("implicit_needs must be a list")

    description_fit_score = data.get("description_fit_score", 0.0)
    if not isinstance(description_fit_score, (int, float)):
        description_fit_score = 0.0
    description_fit_score = max(0.0, min(float(description_fit_score), 1.0))

    skill_categories = _categorize_skills(extracted_skills, core_skills, adjacent_skills)

    return ContractAnalysis(
        extracted_skills=extracted_skills,
        skill_categories=skill_categories,
        client_problem=client_problem,
        implicit_needs=implicit_needs,
        description_fit_score=description_fit_score,
    )
