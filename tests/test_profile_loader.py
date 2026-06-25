"""Tests for the profile loader (backend.portfolio.profile_loader)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from backend.portfolio.profile_loader import (
    ADJACENT_SKILL_WEIGHT,
    ADJACENT_SKILLS,
    CORE_SKILL_WEIGHT,
    ProfileLoadError,
    load_profile,
)


# ── Fixture: synthetic profile.yaml (publishable; no author PII) ──────────────

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_FIXTURE_PROFILE = _PROJECT_ROOT / "tests" / "fixtures" / "profile" / "profile.yaml"


# ── Loading from valid YAML ──────────────────────────────────────────────────


def test_load_real_profile():
    """load_profile succeeds with the synthetic fixture profile.yaml."""
    profile = load_profile(_FIXTURE_PROFILE)
    assert profile.name == "Pat"
    assert profile.studio == "Sample Studio"
    assert len(profile.hourly_rate_range) == 2
    assert profile.key_differentiators  # not empty


def test_core_skills_extracted():
    """Core skills are all skills listed under key_differentiators, weight 1.0."""
    profile = load_profile(_FIXTURE_PROFILE)
    core_names = [s.name for s in profile.core_skills]
    # Should contain known skills from the real profile
    assert "Power BI" in core_names
    assert "Python" in core_names
    assert "SQL" in core_names
    for skill in profile.core_skills:
        assert skill.weight == CORE_SKILL_WEIGHT


def test_core_skills_are_unique():
    """Duplicate skills across categories appear only once."""
    profile = load_profile(_FIXTURE_PROFILE)
    core_names = [s.name for s in profile.core_skills]
    assert len(core_names) == len(set(core_names))


def test_adjacent_skills_populated():
    """Adjacent skills list is populated with correct weight."""
    profile = load_profile(_FIXTURE_PROFILE)
    assert len(profile.adjacent_skills) == len(ADJACENT_SKILLS)
    for skill in profile.adjacent_skills:
        assert skill.weight == ADJACENT_SKILL_WEIGHT
    adjacent_names = {s.name for s in profile.adjacent_skills}
    assert adjacent_names == set(ADJACENT_SKILLS)


def test_all_skills_is_union():
    """all_skills contains every core and adjacent skill exactly once (no duplicates)."""
    profile = load_profile(_FIXTURE_PROFILE)
    all_names = [s.name.lower() for s in profile.all_skills]
    # No duplicates in the combined list.
    assert len(all_names) == len(set(all_names))
    # Every core skill is present.
    core_names = {s.name.lower() for s in profile.core_skills}
    assert core_names <= set(all_names)
    # Adjacent skills that aren't already covered by core are also present.
    adjacent_names = {s.name.lower() for s in profile.adjacent_skills}
    expected_adjacent = adjacent_names - core_names
    assert expected_adjacent <= set(all_names)
    # Length equals core + non-overlapping adjacent.
    assert len(profile.all_skills) == len(profile.core_skills) + len(expected_adjacent)


def test_key_differentiators_parsed():
    """key_differentiators has expected categories with SkillProfile objects."""
    profile = load_profile(_FIXTURE_PROFILE)
    assert "reporting" in profile.key_differentiators
    assert "ai" in profile.key_differentiators
    rpt = profile.key_differentiators["reporting"]
    assert rpt.description
    assert isinstance(rpt.skills, list)
    assert len(rpt.skills) > 0


# ── Loading from custom YAML (tmp_path) ─────────────────────────────────────


def test_load_custom_yaml(tmp_path: Path):
    """Profile loader works with an arbitrary valid YAML file."""
    custom = tmp_path / "profile.yaml"
    custom.write_text(
        textwrap.dedent("""\
        name: Test
        studio: Test Studio
        positioning: "Testing"
        hourly_rate_range: [50, 100]
        tone: friendly
        selling_points:
          - "Great at tests"
        key_differentiators:
          testing:
            description: "Test skills"
            skills:
              - pytest
              - unittest
        """),
        encoding="utf-8",
    )
    profile = load_profile(custom)
    assert profile.name == "Test"
    assert len(profile.core_skills) == 2
    assert profile.core_skills[0].name == "pytest"
    assert profile.core_skills[1].name == "unittest"


# ── Error handling ───────────────────────────────────────────────────────────


def test_missing_file_raises():
    """ProfileLoadError is raised when the file does not exist."""
    with pytest.raises(ProfileLoadError, match="not found"):
        load_profile("/nonexistent/path/profile.yaml")


def test_invalid_yaml_raises(tmp_path: Path):
    """ProfileLoadError is raised for malformed YAML."""
    bad = tmp_path / "bad.yaml"
    bad.write_text(":\n  - :\n  bad: [unterminated", encoding="utf-8")
    with pytest.raises(ProfileLoadError):
        load_profile(bad)


def test_non_mapping_yaml_raises(tmp_path: Path):
    """ProfileLoadError when top-level YAML is a list, not a mapping."""
    bad = tmp_path / "list.yaml"
    bad.write_text("- item1\n- item2\n", encoding="utf-8")
    with pytest.raises(ProfileLoadError, match="mapping"):
        load_profile(bad)


# ── Edge cases ───────────────────────────────────────────────────────────────


def test_empty_differentiators(tmp_path: Path):
    """Profile with no key_differentiators yields empty core_skills."""
    minimal = tmp_path / "minimal.yaml"
    minimal.write_text(
        textwrap.dedent("""\
        name: Minimal
        studio: ""
        positioning: ""
        hourly_rate_range: [0, 0]
        tone: ""
        selling_points: []
        key_differentiators: {}
        """),
        encoding="utf-8",
    )
    profile = load_profile(minimal)
    assert profile.core_skills == []
    assert len(profile.adjacent_skills) == len(ADJACENT_SKILLS)
