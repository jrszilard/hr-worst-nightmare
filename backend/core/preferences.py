"""Pure math for the like/dislike learned-preference layer.

A like/dislike on a job adjusts per-skill weights; those weights bias
``job_priority`` at read time. No DB here — callers pass already-normalized
skill names (see ``matching.normalize_skill``) and persist via PreferenceStore.
"""

from __future__ import annotations

STEP = 0.25      # per-skill weight change for one like/dislike
MAX_WEIGHT = 1.0  # clamp bound for an individual skill weight
ALPHA = 0.3       # how hard the mean bias nudges job_priority


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(x, hi))


def _feedback_sign(feedback: str | None) -> float:
    """+1 liked, -1 disliked, 0 cleared/unknown."""
    if feedback == "liked":
        return 1.0
    if feedback == "disliked":
        return -1.0
    return 0.0


def apply_feedback(
    weights: dict[str, float],
    skills: list[str],
    old_fb: str | None,
    new_fb: str | None,
) -> dict[str, float]:
    """Return updated weights: reverse old feedback's contribution, apply new.

    Per-skill change is ``STEP * (sign(new) - sign(old))`` so toggling in one
    request lands at the right place. Each weight is clamped to
    ``[-MAX_WEIGHT, MAX_WEIGHT]``. Reversal is exact except near the clamp bound.
    """
    delta = STEP * (_feedback_sign(new_fb) - _feedback_sign(old_fb))
    out = dict(weights)
    if delta == 0.0:
        return out
    for skill in set(skills):
        out[skill] = _clamp(out.get(skill, 0.0) + delta, -MAX_WEIGHT, MAX_WEIGHT)
    return out


def preference_bias(weights: dict[str, float], skills: list[str]) -> float:
    """Mean learned weight over the job's (normalized) skills, in [-1, 1]. 0 if none."""
    unique = set(skills)
    if not unique:
        return 0.0
    return sum(weights.get(s, 0.0) for s in unique) / len(unique)


def biased_priority(base: float, bias: float, alpha: float = ALPHA) -> float:
    """Nudge a base priority by the bias, clamped to [0, 1]. bias==0 → unchanged."""
    return _clamp(base + alpha * bias, 0.0, 1.0)
