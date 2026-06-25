"""Skill matching logic for contract-to-profile comparison.

Given a contract's required skills and a freelancer's loaded profile,
calculate how well the profile matches the contract requirements.

Uses substring matching and an alias map so that "Microsoft Power BI"
matches the core skill "Power BI", and "Power Query" maps to "Power BI".
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.core.models import LoadedProfile


# ── Skill aliases ───────────────────────────────────────────────────────────
# Maps common Upwork skill tag variations to the canonical skill name used
# in profile.yaml.  All keys and values should be lowercase.
SKILL_ALIASES: dict[str, str] = {
    "microsoft power bi": "power bi",
    "microsoft power bi data visualization": "power bi",
    "microsoft power bi development": "power bi",
    "power bi data visualization": "power bi",
    "power bi development": "power bi",
    "power query": "power bi",
    "advanced excel": "excel",
    "microsoft excel": "excel",
    "excel vba": "excel",
    "google sheets": "excel",
    "tableau desktop": "tableau",
    "tableau server": "tableau",
    "tableau prep": "tableau",
    "dashboard": "data visualization",
    "dashboard design": "data visualization",
    "data visualization framework": "data visualization",
    "business intelligence": "data analysis",
    "data analytics": "data analysis",
    "machine learning": "general data science",
    "deep learning": "general data science",
    "ml": "general data science",
    "nlp": "ai agents",
    "chatbot development": "ai agents",
    # AI-pivot vocabulary — modern Upwork tags for LLM/agent work.
    "rag": "rag pipelines",
    "retrieval augmented generation": "rag pipelines",
    "retrieval-augmented generation": "rag pipelines",
    "semantic search": "rag pipelines",
    "vector database": "rag pipelines",
    "vector databases": "rag pipelines",
    "agentic": "ai agents",
    "agentic ai": "ai agents",
    "agentic workflows": "ai agents",
    "ai agent": "ai agents",
    "ai agent development": "ai agents",
    "generative ai": "ai agents",
    "llm": "anthropic claude api",
    "large language models": "anthropic claude api",
    "llm development": "anthropic claude api",
    "prompt engineering": "anthropic claude api",
    "langchain": "langchain",
    "openai api": "openai api",
    "anthropic claude api": "anthropic claude api",
    "rest apis": "rest apis",
    "api integration": "rest apis",
    "api": "rest apis",
    "database design": "database design",
    "postgresql": "sql",
    "mysql": "sql",
    "sql server": "sql",
    "ms sql": "sql",
    "data modeling": "data modeling",
    "dax": "dax",
    "process automation": "process automation",
    "workflow automation": "process automation",
}


@dataclass
class MatchResult:
    """Result of matching contract skills against a profile."""

    match_score: float
    core_hits: list[str] = field(default_factory=list)
    adjacent_hits: list[str] = field(default_factory=list)
    unmatched: list[str] = field(default_factory=list)


def _normalize_skill(skill: str) -> str:
    """Resolve a contract skill to its canonical form via aliases."""
    lower = skill.lower().strip()
    # Direct alias lookup first.
    if lower in SKILL_ALIASES:
        return SKILL_ALIASES[lower]
    return lower


# Public alias — the preference layer normalizes job skills to the matcher's
# canonical vocabulary so learned-weight keys line up with matching.
normalize_skill = _normalize_skill


def _substring_match(skill_lower: str, names: set[str]) -> bool:
    """Check if skill matches any name via substring containment.

    Matches if:
    - exact match: "power bi" in {"power bi"}
    - contract skill contains a profile skill: "microsoft power bi" contains "power bi"
    - profile skill contains the contract skill: "data visualization" contains "data"
      (only if contract skill is 4+ chars to avoid false positives)
    """
    if skill_lower in names:
        return True
    # Contract skill contains a profile skill name
    for name in names:
        if name in skill_lower:
            return True
    # Profile skill contains the contract skill (only for longer terms)
    if len(skill_lower) >= 4:
        for name in names:
            if skill_lower in name:
                return True
    return False


def calculate_match_score(
    contract_skills: list[str],
    profile: LoadedProfile,
) -> MatchResult:
    """Calculate how well a profile matches a contract's required skills.

    Formula:
        match_score = min(
            (core_hits * 1.0 + adjacent_hits * 0.6) / total_extracted_skills,
            1.0,
        )

    Uses a three-step matching strategy:
    1. Alias resolution — maps common variations to canonical names
    2. Exact match — against core and adjacent skill sets
    3. Substring match — "Microsoft Power BI" contains "Power BI"
    """
    if not contract_skills:
        return MatchResult(match_score=0.0)

    # Build case-insensitive lookup sets from the profile.
    core_names = {s.name.lower() for s in profile.core_skills}
    adjacent_names = {s.name.lower() for s in profile.adjacent_skills}

    core_hits: list[str] = []
    adjacent_hits: list[str] = []
    unmatched: list[str] = []

    for skill in contract_skills:
        # Step 1: Normalize via alias map
        normalized = _normalize_skill(skill)

        # Step 2: Check exact match on normalized name
        if normalized in core_names:
            core_hits.append(skill)
        elif normalized in adjacent_names:
            adjacent_hits.append(skill)
        # Step 3: Fall back to substring matching on original name
        elif _substring_match(skill.lower(), core_names):
            core_hits.append(skill)
        elif _substring_match(skill.lower(), adjacent_names):
            adjacent_hits.append(skill)
        else:
            unmatched.append(skill)

    total = len(contract_skills)
    raw_score = (len(core_hits) * 1.0 + len(adjacent_hits) * 0.6) / total
    match_score = min(raw_score, 1.0)

    return MatchResult(
        match_score=match_score,
        core_hits=core_hits,
        adjacent_hits=adjacent_hits,
        unmatched=unmatched,
    )
