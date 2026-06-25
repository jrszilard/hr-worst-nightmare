"""Tests for the pure preference-weight math (no DB)."""

import pytest

from backend.core.preferences import (
    ALPHA,
    STEP,
    apply_feedback,
    biased_priority,
    preference_bias,
)


def test_like_adds_step_to_each_skill():
    out = apply_feedback({}, ["sql", "python"], old_fb=None, new_fb="liked")
    assert out == {"sql": STEP, "python": STEP}


def test_dislike_subtracts_step():
    out = apply_feedback({}, ["sales"], old_fb=None, new_fb="disliked")
    assert out == {"sales": -STEP}


def test_clearing_like_reverses_it():
    weights = {"sql": STEP}
    out = apply_feedback(weights, ["sql"], old_fb="liked", new_fb=None)
    assert out["sql"] == 0.0


def test_toggle_like_to_dislike_is_one_full_swing():
    weights = {"sql": STEP}
    out = apply_feedback(weights, ["sql"], old_fb="liked", new_fb="disliked")
    assert out["sql"] == -STEP


def test_same_feedback_is_noop():
    weights = {"sql": STEP}
    out = apply_feedback(weights, ["sql"], old_fb="liked", new_fb="liked")
    assert out["sql"] == STEP


def test_weight_clamps_to_unit_bounds():
    weights = {"sql": 0.9}
    out = apply_feedback(weights, ["sql"], old_fb=None, new_fb="liked")
    assert out["sql"] == 1.0  # 0.9 + 0.25 clamped to 1.0


def test_duplicate_skills_apply_once():
    out = apply_feedback({}, ["sql", "sql"], old_fb=None, new_fb="liked")
    assert out["sql"] == STEP


def test_preference_bias_is_mean_over_skills():
    weights = {"sql": 0.5, "python": 0.1}
    assert preference_bias(weights, ["sql", "python"]) == 0.3


def test_preference_bias_zero_when_no_skills_or_signal():
    assert preference_bias({"sql": 0.5}, []) == 0.0
    assert preference_bias({}, ["unknown"]) == 0.0


def test_biased_priority_unchanged_when_bias_zero():
    assert biased_priority(0.7, 0.0) == 0.7


def test_biased_priority_nudges_by_alpha():
    assert biased_priority(0.5, 1.0) == pytest.approx(0.5 + ALPHA)
    assert biased_priority(0.5, -1.0) == pytest.approx(0.5 - ALPHA)


def test_weight_clamps_to_negative_unit_bound():
    weights = {"sql": -0.9}
    out = apply_feedback(weights, ["sql"], old_fb=None, new_fb="disliked")
    assert out["sql"] == -1.0  # -0.9 - 0.25 clamped to -1.0


def test_biased_priority_clamps():
    assert biased_priority(0.95, 1.0) == 1.0
    assert biased_priority(0.05, -1.0) == 0.0
