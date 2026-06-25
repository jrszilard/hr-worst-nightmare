"""AI-powered proposal generation — creates tailored proposals with annotations."""

from __future__ import annotations

import functools
import json
import logging
from pathlib import Path

import anthropic
from pydantic import BaseModel

from backend.ai.json_utils import extract_json_object
from backend.ai.usage import record_usage
from backend.ai.writing.style import style_rules_text
from backend.config import settings
from backend.core.enums import ProposalSectionType
from backend.core.models import (
    AvailabilityConfig,
    Contract,
    LoadedProfile,
    ProposalSection,
)
from backend.portfolio.case_study_loader import (
    DetailedCaseStudy,
    format_case_studies_for_prompt,
    load_all_case_studies,
)

logger = logging.getLogger(__name__)

# ── Prompt template ─────────────────────────────────────────────────────────

_PROMPT_PATH = Path(__file__).parent / "prompts" / "proposal_generation.txt"


@functools.lru_cache(maxsize=1)
def _load_prompt() -> str:
    """Load the proposal generation prompt template (cached after first read)."""
    return _PROMPT_PATH.read_text(encoding="utf-8")


# ── Result model ────────────────────────────────────────────────────────────


class GeneratedProposal(BaseModel):
    """Structured result of AI proposal generation."""

    sections: list[ProposalSection]
    bid_amount: float
    estimated_duration: str


# ── Helpers ─────────────────────────────────────────────────────────────────


def _format_budget_range(contract: Contract) -> str:
    """Format the contract budget range for the prompt."""
    if contract.budget_min is not None and contract.budget_max is not None:
        return f"${contract.budget_min:.0f}-${contract.budget_max:.0f}"
    if contract.budget_min is not None:
        return f"${contract.budget_min:.0f}+"
    if contract.budget_max is not None:
        return f"Up to ${contract.budget_max:.0f}"
    return "Not specified"


def _validate_case_study_ids(
    sections: list[dict],
    valid_slugs: set[str],
) -> list[dict]:
    """Filter out case_study_ids that don't reference real case studies."""
    for section in sections:
        ids = section.get("case_study_ids", [])
        if ids:
            section["case_study_ids"] = [sid for sid in ids if sid in valid_slugs]
    return sections


# ── Public API ──────────────────────────────────────────────────────────────


async def generate_proposal(
    contract: Contract,
    profile: LoadedProfile,
    availability: AvailabilityConfig,
    client: anthropic.AsyncAnthropic | None = None,
    detailed_case_studies: list[DetailedCaseStudy] | None = None,
) -> GeneratedProposal:
    """Generate a tailored proposal for a contract using Claude.

    Parameters
    ----------
    contract:
        The full contract to write a proposal for.
    profile:
        The freelancer's loaded profile.
    availability:
        The freelancer's availability and rate configuration.
    client:
        Optional pre-configured AsyncAnthropic client (useful for testing).
    detailed_case_studies:
        File-based detailed case studies to reference; loaded from disk when None.

    Returns
    -------
    GeneratedProposal
        Contains structured proposal sections with annotations, suggested bid,
        and estimated duration.

    Raises
    ------
    ValueError
        If Claude's response cannot be parsed as valid JSON or is missing
        required fields.
    """
    prompt_template = _load_prompt()

    # Build differentiators summary
    diff_parts: list[str] = []
    for key, sp in profile.key_differentiators.items():
        diff_parts.append(f"{key}: {sp.description}")
    key_diff_str = "; ".join(diff_parts) if diff_parts else "N/A"

    # Use the file-based detailed markdown case studies.
    if detailed_case_studies is None:
        detailed_case_studies = load_all_case_studies()
    case_studies_text = format_case_studies_for_prompt(detailed_case_studies)
    # Build valid slugs from detailed studies for honesty guard
    all_valid_slugs = {cs.slug for cs in detailed_case_studies}

    user_message = prompt_template.format(
        style_rules=style_rules_text(profile),
        name=profile.name,
        studio=profile.studio,
        positioning=profile.positioning,
        tone=profile.tone,
        selling_points=", ".join(profile.selling_points),
        key_differentiators=key_diff_str,
        rate_min=profile.hourly_rate_range[0] if profile.hourly_rate_range else 0,
        rate_max=profile.hourly_rate_range[1] if len(profile.hourly_rate_range) > 1 else 0,
        hours_per_week=availability.hours_per_week,
        min_hourly_rate=availability.min_hourly_rate,
        min_fixed_budget=availability.min_fixed_budget,
        case_studies=case_studies_text,
        contract_title=contract.title or "Untitled",
        contract_description=contract.description or "No description provided",
        contract_skills=", ".join(contract.skills_required) if contract.skills_required else "None listed",
        budget_range=_format_budget_range(contract),
        contract_duration=contract.duration or "Not specified",
        contract_type=contract.contract_type.value if contract.contract_type else "Not specified",
    )

    if client is None:
        client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    response = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": user_message}],
    )
    record_usage("claude-sonnet-4-6", response)

    # Extract text from Claude's response
    if not response.content:
        raise ValueError("Claude returned an empty response")
    raw_text = response.content[0].text

    try:
        data = extract_json_object(raw_text)
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse Claude response as JSON: %s", raw_text[:500])
        raise ValueError(f"Claude returned invalid JSON: {exc}") from exc

    # Validate sections
    raw_sections = data.get("sections")
    if not isinstance(raw_sections, list) or len(raw_sections) != 5:
        raise ValueError("Response must contain exactly 5 sections")

    # Build set of valid case study slugs for honesty guard
    raw_sections = _validate_case_study_ids(raw_sections, all_valid_slugs)

    # Parse sections into ProposalSection models
    sections: list[ProposalSection] = []
    expected_types = {"hook", "experience", "approach", "differentiator", "cta"}
    seen_types: set[str] = set()

    for raw_section in raw_sections:
        section_type = raw_section.get("type", "")
        if section_type not in expected_types:
            raise ValueError(f"Invalid section type: {section_type}")
        if section_type in seen_types:
            raise ValueError(f"Duplicate section type: {section_type}")
        seen_types.add(section_type)

        sections.append(
            ProposalSection(
                type=ProposalSectionType(section_type),
                content=raw_section.get("content", ""),
                annotation=raw_section.get("annotation"),
                case_study_ids=raw_section.get("case_study_ids", []),
            )
        )

    # Validate bid_amount and estimated_duration
    bid_amount = data.get("bid_amount")
    if not isinstance(bid_amount, (int, float)):
        raise ValueError("bid_amount must be a number")

    estimated_duration = data.get("estimated_duration")
    if not isinstance(estimated_duration, str):
        raise ValueError("estimated_duration must be a string")

    return GeneratedProposal(
        sections=sections,
        bid_amount=float(bid_amount),
        estimated_duration=estimated_duration,
    )
