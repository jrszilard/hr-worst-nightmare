"""Deterministic job-fit scoring for full-time / staff job postings.

Board-scanned jobs have no AI ``description_fit`` (generation is deferred to
apply-time to stay free), so ``job_priority`` used to collapse to the
self-referential ``match_score`` — which is ~1.0 for almost every posting because
skills are extracted *from* the profile vocabulary. The result was a useless
ranking where ~64% of candidates tied at 1.00.

``job_fit_score`` produces a spread-out fit signal with no LLM calls, blending:
  - title relevance   (is this the kind of role we target?)
  - skill depth       (how many of our *core* skills does it actually demand?)
  - seniority fit     (penalize intern/new-grad and exec roles)

Returned in [0.0, 1.0]; wired in as the deterministic ``description_fit`` so the
existing ``job_priority = 0.5*match + 0.5*description_fit`` blend ranks sensibly.
"""

from __future__ import annotations

from backend.core.models import LoadedProfile

# Titles squarely in the target lane (data / analytics / BI / AI / forward-deployed).
_STRONG_TITLE = (
    "data analyst", "business intelligence", "bi ", "bi,", "analytics engineer",
    "analytics", "data scientist", "ai engineer", "ml engineer",
    "machine learning engineer", "ai solutions", "solutions architect",
    "solutions engineer", "solutions consultant", "forward deployed", "fde",
    "data engineer", "data visualization", "reporting", "ai/ml", "data platform",
)
# Adjacent / plausible but not a bullseye.
_MEDIUM_TITLE = (
    "software engineer", "product analyst", "research engineer", "platform engineer",
    "automation", "data infrastructure", "applied scientist", "developer",
    "integration engineer", "implementation",
)
# Out-of-lane roles — drag the score to the floor regardless of skill keywords.
_ANTI_TITLE = (
    "intern", "new grad", "new-grad", "university", "graduate", "early career",
    "apprentice", "recruit", "sales", "account executive", "account manager",
    "customer success", "people analytics", "hr ", "human resources", "payroll",
    "marketing", "legal", "counsel", "support specialist", "technical support",
    "executive assistant", "office", "facilities", "procurement",
)
_JUNIOR = ("intern", "new grad", "new-grad", "graduate", "early career", "apprentice")
_EXEC = ("director", "vp", "vice president", "head of", "chief", "president")

_SKILL_DEPTH_TARGET = 4.0  # weighted core+adjacent skills that count as "deep fit"


def _contains_any(haystack: str, needles) -> bool:
    return any(n in haystack for n in needles)


def _title_fit(title_lower: str) -> float:
    if not title_lower:
        return 0.3
    if _contains_any(title_lower, _ANTI_TITLE):
        return 0.0
    if _contains_any(title_lower, _STRONG_TITLE):
        return 1.0
    if _contains_any(title_lower, _MEDIUM_TITLE):
        return 0.6
    return 0.3


def _seniority_multiplier(title_lower: str) -> float:
    if _contains_any(title_lower, _JUNIOR):
        return 0.35
    if _contains_any(title_lower, _EXEC):
        return 0.6
    return 1.0


def _skill_depth(skills_required: list[str], profile: LoadedProfile) -> float:
    core = {s.name.lower() for s in profile.core_skills}
    adjacent = {s.name.lower() for s in profile.adjacent_skills}
    seen: set[str] = set()
    weighted = 0.0
    for skill in skills_required or []:
        key = skill.lower().strip()
        if key in seen:
            continue
        seen.add(key)
        if key in core:
            weighted += 1.0
        elif key in adjacent:
            weighted += 0.5
    return min(weighted / _SKILL_DEPTH_TARGET, 1.0)


def job_fit_score(
    title: str | None,
    description: str | None,
    skills_required: list[str],
    profile: LoadedProfile,
) -> float:
    """Deterministic [0,1] fit score used as ``description_fit`` for jobs."""
    title_lower = (title or "").lower()
    title_fit = _title_fit(title_lower)
    depth = _skill_depth(skills_required, profile)
    base = 0.55 * title_fit + 0.45 * depth
    score = base * _seniority_multiplier(title_lower)
    return max(0.0, min(score, 1.0))
