"""ROI scoring, win-probability, and availability filtering.

Provides the financial scoring layer that sits on top of the skill matching
engine.  Given a match_score and contract metadata, produce an roi_score
that captures the expected value of applying to a contract.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

from backend.core.enums import ContractType, PreferredContractType
from backend.core.models import AvailabilityConfig, Contract


@dataclass
class ScoringResult:
    """Result of ROI scoring for a single contract."""

    win_probability: float
    roi_score: float
    contract_value: float
    connects_cost: float
    time_cost: float


# ── Win probability ──────────────────────────────────────────────────────────


def calculate_win_probability(
    match_score: float,
    client_hire_rate: float,
    proposals_count: int,
    description_fit: float | None = None,
) -> float:
    """Compute the estimated probability of winning a contract.

    When *description_fit* is provided (from AI analysis), the effective
    match uses a 40/60 blend of skill-tag match and description fit.
    When absent, skill match is used alone (backward-compatible).

    Formula:
        if description_fit is not None:
            combined = match_score * 0.4 + description_fit * 0.6
        else:
            combined = match_score
        win_probability = min(combined * client_hire_rate * (1 / log2(proposals_count + 2)), 1.0)
    """
    if proposals_count < 0:
        proposals_count = 0

    if description_fit is not None:
        combined = match_score * 0.4 + description_fit * 0.6
    else:
        combined = match_score

    win_prob = (
        combined
        * client_hire_rate
        * (1.0 / math.log2(proposals_count + 2))
    )
    return max(0.0, min(win_prob, 1.0))


# ── Contract value estimation ────────────────────────────────────────────────


def estimate_contract_value(contract: Contract) -> float:
    """Estimate the total monetary value of a contract.

    - Fixed contracts: ``budget_max`` (or 0 if absent).
    - Hourly contracts: ``budget_max * 160`` (monthly equivalent).
    """
    if contract.contract_type is None:
        return 0.0

    budget = contract.budget_max or 0.0

    if contract.contract_type == ContractType.hourly:
        return budget * 160.0
    # Fixed — use budget_max directly.
    return budget


# ── ROI scoring ──────────────────────────────────────────────────────────────


def calculate_roi_score(
    match_score: float,
    contract: Contract,
    availability: AvailabilityConfig,
) -> ScoringResult:
    """Calculate the ROI score for applying to a contract.

    Formula:
        roi_score = (match_score * contract_value * win_probability)
                    / (connects_cost + time_cost)

    Where:
        - contract_value = budget_max (fixed) or hourly_rate * 160 (hourly)
        - connects_cost  = connects_cost_int * 0.15
        - time_cost      = 0.25 hours * hourly_value
        - win_probability uses ``calculate_win_probability``

    Edge case: if the denominator is 0, roi_score = 0.
    """
    contract_value = estimate_contract_value(contract)

    connects_int = contract.connects_cost or 0
    connects_cost = connects_int * 0.15

    time_cost = 0.25 * availability.hourly_value

    # Default missing hire rate to 0.5 (Upwork average) rather than 0.0
    # to avoid zeroing out win_probability for unscraped fields.
    client_hire_rate = contract.client_hire_rate if contract.client_hire_rate is not None else 0.5
    proposals_count = contract.proposals_count or 0

    win_probability = calculate_win_probability(
        match_score, client_hire_rate, proposals_count
    )

    denominator = connects_cost + time_cost
    if denominator == 0:
        roi_score = 0.0
    else:
        roi_score = (match_score * contract_value * win_probability) / denominator

    return ScoringResult(
        win_probability=win_probability,
        roi_score=roi_score,
        contract_value=contract_value,
        connects_cost=connects_cost,
        time_cost=time_cost,
    )


# ── Job ranking (fit, not connects-ROI) ─────────────────────────────────────


def calculate_job_priority(
    match_score: float,
    description_fit: float | None = None,
) -> float:
    """Ranking score for full-time / contract JOBS.

    Jobs are not a connects-spend problem, so we rank by fit rather than a
    dollar ROI (which would be mostly noise without connects, hire-rate, or a
    meaningful per-application cost). Blends skill-tag match with the AI
    ``description_fit`` when available, otherwise uses skill match alone.
    Returns a value in ``[0.0, 1.0]``.

    Comp floor / work-mode / seniority *gating* is a separate filter applied
    once those preferences and board-populated ``platform_meta`` fields exist.
    """
    if description_fit is not None:
        score = 0.5 * match_score + 0.5 * description_fit
    else:
        score = match_score
    return max(0.0, min(score, 1.0))


# ── Percentile-based indicators ─────────────────────────────────────────────


def assign_indicator(roi_score: float, all_scores: list[float]) -> str:
    """Assign a green / yellow / red indicator based on percentile rank.

    - Green:  top 25 %  (above 75th percentile)
    - Yellow: middle 50 % (25th to 75th percentile, inclusive)
    - Red:    bottom 25 % (below 25th percentile)

    If *all_scores* is empty, returns ``"red"``.
    """
    if not all_scores:
        return "red"

    if len(all_scores) < 2:
        # statistics.quantiles requires at least 2 data points; treat the
        # single score as the only reference point — everything is middle.
        return "yellow"

    quartiles = statistics.quantiles(all_scores, n=4)  # returns [p25, p50, p75]
    p25, p75 = quartiles[0], quartiles[2]

    if roi_score > p75:
        return "green"
    elif roi_score < p25:
        return "red"
    return "yellow"


# ── Availability filter ─────────────────────────────────────────────────────


def passes_availability_filter(
    contract: Contract,
    availability: AvailabilityConfig,
) -> bool:
    """Check whether a contract passes the freelancer's availability filter.

    Checks:
    1. Budget meets rate floor.
       - Hourly: ``budget_max >= min_hourly_rate``
       - Fixed:  ``budget_max >= min_fixed_budget``
    2. Contract type matches preference (``"both"`` always passes).
    """
    # ── Contract-type preference ────────────────────────────────────────
    if availability.preferred_contract_type != PreferredContractType.both:
        if contract.contract_type is not None:
            if contract.contract_type.value != availability.preferred_contract_type.value:
                return False

    # ── Rate floor ──────────────────────────────────────────────────────
    budget = contract.budget_max
    if budget is not None:
        if contract.contract_type == ContractType.hourly:
            if budget < availability.min_hourly_rate:
                return False
        elif contract.contract_type == ContractType.fixed:
            if budget < availability.min_fixed_budget:
                return False

    return True
