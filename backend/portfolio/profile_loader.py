"""Load and validate the freelancer skills profile from data/profile.yaml.

Exposes ``get_profile`` as a FastAPI dependency that returns a cached
``LoadedProfile`` instance.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import yaml

from backend.core.models import ApplicantInfo, LoadedProfile, SkillProfile, WeightedSkill
from backend.core.profile_context import get_profile_context

# Adjacent skills that are related but not listed under key_differentiators.
# These receive a lower weight (0.6) in the scoring engine.
ADJACENT_SKILLS: list[str] = [
    "General Python development",
    "Data analysis",
    "Pandas",
    "Chatbot development",
    "Web scraping",
    "Automation",
    "General data science",
]

CORE_SKILL_WEIGHT = 1.0
ADJACENT_SKILL_WEIGHT = 0.6


class ProfileLoadError(Exception):
    """Raised when the profile YAML cannot be loaded or validated."""


def _extract_core_skills(differentiators: dict[str, Any]) -> list[WeightedSkill]:
    """Extract unique core skills from key_differentiators, preserving order."""
    seen: set[str] = set()
    skills: list[WeightedSkill] = []
    for _category, data in differentiators.items():
        for skill_name in data.get("skills", []):
            if skill_name not in seen:
                seen.add(skill_name)
                skills.append(WeightedSkill(name=skill_name, weight=CORE_SKILL_WEIGHT))
    return skills


def _build_adjacent_skills() -> list[WeightedSkill]:
    """Build weighted adjacent skill list."""
    return [
        WeightedSkill(name=name, weight=ADJACENT_SKILL_WEIGHT)
        for name in ADJACENT_SKILLS
    ]


def load_profile(path: Path | str | None = None) -> LoadedProfile:
    """Read *profile.yaml*, validate, and return a ``LoadedProfile``.

    Parameters
    ----------
    path:
        Optional override for the YAML file location.  Defaults to
        ``data/profile.yaml`` relative to the project root.

    Raises
    ------
    ProfileLoadError
        If the file is missing, unreadable, or fails validation.
    """
    profile_path = Path(path) if path is not None else get_profile_context().profile_yaml

    if not profile_path.exists():
        raise ProfileLoadError(f"Profile file not found: {profile_path}")

    try:
        raw: dict[str, Any] = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ProfileLoadError(f"Invalid YAML in {profile_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ProfileLoadError(f"Expected a YAML mapping at top level, got {type(raw).__name__}")

    # Parse key_differentiators into SkillProfile models.
    differentiators_raw = raw.get("key_differentiators", {})
    differentiators: dict[str, SkillProfile] = {}
    for key, value in differentiators_raw.items():
        differentiators[key] = SkillProfile(
            description=value.get("description", ""),
            skills=value.get("skills", []),
        )

    core_skills = _extract_core_skills(differentiators_raw)
    adjacent_skills = _build_adjacent_skills()
    core_names = {s.name.lower() for s in core_skills}
    adjacent_filtered = [s for s in adjacent_skills if s.name.lower() not in core_names]
    all_skills = core_skills + adjacent_filtered

    hourly_rate_range = raw.get("hourly_rate_range", [75, 150])
    applicant = ApplicantInfo(**(raw.get("applicant") or {}))

    return LoadedProfile(
        name=raw.get("name", ""),
        studio=raw.get("studio", ""),
        positioning=raw.get("positioning", ""),
        location=raw.get("location", ""),
        voice=raw.get("voice", ""),
        framing=raw.get("framing", ""),
        hourly_rate_range=hourly_rate_range,
        tone=raw.get("tone", ""),
        selling_points=raw.get("selling_points", []),
        key_differentiators=differentiators,
        core_skills=core_skills,
        adjacent_skills=adjacent_skills,
        all_skills=all_skills,
        applicant=applicant,
    )


@functools.lru_cache(maxsize=1)
def _cached_profile() -> LoadedProfile:
    """Load the profile once and cache it for the process lifetime."""
    return load_profile()


def clear_profile_cache() -> None:
    """Drop the cached profile (call after the profile file is rewritten)."""
    _cached_profile.cache_clear()


def get_profile() -> LoadedProfile:
    """FastAPI dependency — returns the cached ``LoadedProfile``.

    Usage::

        @app.get("/api/profile")
        async def profile(profile: LoadedProfile = Depends(get_profile)):
            return profile
    """
    return _cached_profile()
