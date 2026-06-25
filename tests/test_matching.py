"""Tests for the skill matching engine (backend.core.matching)."""

from __future__ import annotations

import pytest

from backend.core.matching import MatchResult, calculate_match_score
from backend.core.models import LoadedProfile, WeightedSkill


# ── Helpers ──────────────────────────────────────────────────────────────────


def _profile(
    core: list[str] | None = None,
    adjacent: list[str] | None = None,
) -> LoadedProfile:
    """Build a minimal LoadedProfile with the given skill lists."""
    core_skills = [WeightedSkill(name=s, weight=1.0) for s in (core or [])]
    adjacent_skills = [WeightedSkill(name=s, weight=0.6) for s in (adjacent or [])]
    return LoadedProfile(
        name="Test User",
        studio="Test Studio",
        positioning="Test positioning",
        hourly_rate_range=[100.0, 150.0],
        tone="professional",
        selling_points=["point1"],
        key_differentiators={},
        core_skills=core_skills,
        adjacent_skills=adjacent_skills,
        all_skills=core_skills + adjacent_skills,
    )


# ── Core skill hits ─────────────────────────────────────────────────────────


def test_all_core_hits():
    """All contract skills match core skills -> score 1.0."""
    profile = _profile(core=["Python", "FastAPI", "React"])
    result = calculate_match_score(["Python", "FastAPI", "React"], profile)

    assert result.match_score == pytest.approx(1.0)
    assert sorted(result.core_hits) == ["FastAPI", "Python", "React"]
    assert result.adjacent_hits == []
    assert result.unmatched == []


def test_single_core_hit():
    """One core hit out of two contract skills."""
    profile = _profile(core=["Python"])
    result = calculate_match_score(["Python", "Java"], profile)

    assert result.match_score == pytest.approx(0.5)
    assert result.core_hits == ["Python"]
    assert result.unmatched == ["Java"]


# ── Adjacent skill hits ─────────────────────────────────────────────────────


def test_all_adjacent_hits():
    """All contract skills match adjacent skills -> score = 0.6."""
    profile = _profile(adjacent=["Docker", "AWS"])
    result = calculate_match_score(["Docker", "AWS"], profile)

    assert result.match_score == pytest.approx(0.6)
    assert sorted(result.adjacent_hits) == ["AWS", "Docker"]
    assert result.core_hits == []
    assert result.unmatched == []


def test_single_adjacent_hit():
    """One adjacent hit out of three contract skills."""
    profile = _profile(adjacent=["Docker"])
    result = calculate_match_score(["Docker", "Java", "Rust"], profile)

    # 0.6 / 3 = 0.2
    assert result.match_score == pytest.approx(0.2)
    assert result.adjacent_hits == ["Docker"]


# ── Mixed hits ───────────────────────────────────────────────────────────────


def test_mixed_core_and_adjacent():
    """Mix of core and adjacent hits."""
    profile = _profile(core=["Python"], adjacent=["Docker"])
    result = calculate_match_score(["Python", "Docker", "Java"], profile)

    # (1 * 1.0 + 1 * 0.6) / 3 = 1.6 / 3 ≈ 0.5333
    assert result.match_score == pytest.approx(1.6 / 3)
    assert result.core_hits == ["Python"]
    assert result.adjacent_hits == ["Docker"]
    assert result.unmatched == ["Java"]


# ── No match ─────────────────────────────────────────────────────────────────


def test_no_match():
    """No contract skills match the profile -> score 0."""
    profile = _profile(core=["Python"], adjacent=["Docker"])
    result = calculate_match_score(["Java", "Rust"], profile)

    assert result.match_score == pytest.approx(0.0)
    assert result.core_hits == []
    assert result.adjacent_hits == []
    assert sorted(result.unmatched) == ["Java", "Rust"]


# ── Score capping at 1.0 ────────────────────────────────────────────────────


def test_score_capped_at_one():
    """Score cannot exceed 1.0 even if the formula would otherwise allow it.

    In practice the formula's numerator can't exceed the denominator with the
    current weights, but this guards the contract:
      all core hits always produce exactly 1.0.
    """
    profile = _profile(core=["A", "B", "C", "D", "E"])
    result = calculate_match_score(["A", "B"], profile)

    assert result.match_score <= 1.0
    assert result.match_score == pytest.approx(1.0)


# ── Case-insensitive matching ────────────────────────────────────────────────


def test_case_insensitive_core():
    """Matching is case-insensitive."""
    profile = _profile(core=["python", "FastAPI"])
    result = calculate_match_score(["PYTHON", "fastapi"], profile)

    assert result.match_score == pytest.approx(1.0)
    assert sorted(r.lower() for r in result.core_hits) == ["fastapi", "python"]


def test_case_insensitive_adjacent():
    """Adjacent matching is also case-insensitive."""
    profile = _profile(adjacent=["Docker"])
    result = calculate_match_score(["DOCKER"], profile)

    assert result.match_score == pytest.approx(0.6)
    assert result.adjacent_hits == ["DOCKER"]


# ── Empty contract skills ────────────────────────────────────────────────────


def test_empty_contract_skills():
    """Empty contract skill list returns score 0 and empty lists."""
    profile = _profile(core=["Python"])
    result = calculate_match_score([], profile)

    assert result.match_score == 0.0
    assert result.core_hits == []
    assert result.adjacent_hits == []
    assert result.unmatched == []


# ── Edge: core takes priority over adjacent ──────────────────────────────────


def test_core_takes_priority_over_adjacent():
    """A skill in both core and adjacent lists counts as core."""
    profile = _profile(core=["Python"], adjacent=["Python"])
    result = calculate_match_score(["Python"], profile)

    # Should match core first (weight 1.0), not adjacent.
    assert result.match_score == pytest.approx(1.0)
    assert result.core_hits == ["Python"]
    assert result.adjacent_hits == []


# ── Public normalize_skill alias ─────────────────────────────────────────────


def test_normalize_skill_public_alias_resolves_aliases():
    from backend.core.matching import normalize_skill
    assert normalize_skill("Microsoft Power BI") == "power bi"
    assert normalize_skill("LLM") == "anthropic claude api"
    assert normalize_skill("Unmapped Thing") == "unmapped thing"
