"""Tests for ROI scoring, indicators, and availability filter (backend.core.scoring)."""

from __future__ import annotations

import math

import pytest

from backend.core.enums import ContractType, PreferredContractType
from backend.core.models import AvailabilityConfig, Contract, ContractCreate
from backend.api.scanner import determine_skip_reason
from backend.core.scoring import (
    ScoringResult,
    assign_indicator,
    calculate_roi_score,
    calculate_win_probability,
    estimate_contract_value,
    passes_availability_filter,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _contract(**overrides) -> Contract:
    """Build a Contract with sensible defaults, overridable by kwargs."""
    defaults = dict(
        id=1,
        platform="upwork",
        external_id="test-123",
        budget_max=5000.0,
        contract_type=ContractType.fixed,
        proposals_count=10,
        client_hire_rate=0.80,
        connects_cost=16,
    )
    defaults.update(overrides)
    return Contract(**defaults)


def _availability(**overrides) -> AvailabilityConfig:
    """Build an AvailabilityConfig with sensible defaults."""
    defaults = dict(
        hours_per_week=40,
        max_concurrent_contracts=3,
        current_committed_hours=0,
        min_hourly_rate=75.0,
        min_fixed_budget=500.0,
        hourly_value=100.0,
    )
    defaults.update(overrides)
    return AvailabilityConfig(**defaults)


# ── Win probability ──────────────────────────────────────────────────────────


class TestWinProbability:
    def test_basic_calculation(self):
        """Known-input check: match=0.8, hire_rate=0.9, proposals=10."""
        result = calculate_win_probability(0.8, 0.9, 10)
        expected = 0.8 * 0.9 * (1.0 / math.log2(12))
        assert result == pytest.approx(expected)

    def test_capped_at_one(self):
        """Win probability cannot exceed 1.0."""
        # match=1.0, hire_rate=1.0, proposals=0 -> 1/(log2(2))=1.0
        result = calculate_win_probability(1.0, 1.0, 0)
        assert result == pytest.approx(1.0)

        # Even more extreme — should still be capped.
        result2 = calculate_win_probability(1.0, 1.0, 0)
        assert result2 <= 1.0

    def test_zero_match_score(self):
        """Zero match score -> zero win probability."""
        result = calculate_win_probability(0.0, 0.9, 5)
        assert result == pytest.approx(0.0)

    def test_zero_hire_rate(self):
        """Client with 0% hire rate -> 0 win probability."""
        result = calculate_win_probability(0.8, 0.0, 5)
        assert result == pytest.approx(0.0)

    def test_zero_proposals(self):
        """Zero proposals means low competition: log2(2) = 1."""
        result = calculate_win_probability(0.5, 0.8, 0)
        expected = 0.5 * 0.8 * (1.0 / math.log2(2))
        assert result == pytest.approx(expected)
        # 0.5 * 0.8 * 1.0 = 0.4
        assert result == pytest.approx(0.4)

    def test_high_proposals_reduces_probability(self):
        """More proposals -> lower win probability."""
        low = calculate_win_probability(0.8, 0.9, 5)
        high = calculate_win_probability(0.8, 0.9, 50)
        assert high < low


# ── Description-fit-aware win probability ──────────────────────────────


class TestWinProbabilityWithDescriptionFit:
    """Tests for calculate_win_probability with description_fit parameter."""

    def test_description_fit_increases_probability(self):
        """High description fit should increase win probability."""
        base = calculate_win_probability(0.5, 0.8, 10)
        enhanced = calculate_win_probability(0.5, 0.8, 10, description_fit=0.9)
        assert enhanced > base

    def test_description_fit_none_uses_skill_match_only(self):
        """When description_fit is None, behavior matches the old formula."""
        result = calculate_win_probability(0.5, 0.8, 10, description_fit=None)
        # Old formula: 0.5 * 0.8 * (1/log2(12)) = 0.5 * 0.8 * 0.279 = 0.1116
        expected = 0.5 * 0.8 * (1.0 / __import__('math').log2(12))
        assert abs(result - expected) < 0.001

    def test_description_fit_zero_lowers_probability(self):
        """Zero description fit with good skill match should lower probability."""
        skill_only = calculate_win_probability(0.8, 0.8, 10, description_fit=None)
        with_zero_fit = calculate_win_probability(0.8, 0.8, 10, description_fit=0.0)
        assert with_zero_fit < skill_only

    def test_combined_match_weighting(self):
        """Combined match should be 40% skill + 60% description_fit."""
        # skill=1.0, desc_fit=0.0 -> combined = 0.4
        # skill=0.0, desc_fit=1.0 -> combined = 0.6
        low_skill = calculate_win_probability(0.0, 0.8, 10, description_fit=1.0)
        low_desc = calculate_win_probability(1.0, 0.8, 10, description_fit=0.0)
        assert low_skill > low_desc  # 0.6 > 0.4


# ── Contract value estimation ────────────────────────────────────────────────


class TestContractValue:
    def test_fixed_contract_value(self):
        """Fixed contract uses budget_max directly."""
        c = _contract(contract_type=ContractType.fixed, budget_max=5000.0)
        assert estimate_contract_value(c) == pytest.approx(5000.0)

    def test_hourly_contract_value(self):
        """Hourly contract: budget_max (hourly rate) * 160."""
        c = _contract(contract_type=ContractType.hourly, budget_max=75.0)
        assert estimate_contract_value(c) == pytest.approx(75.0 * 160)

    def test_no_budget(self):
        """Missing budget -> value 0."""
        c = _contract(budget_max=None)
        assert estimate_contract_value(c) == pytest.approx(0.0)

    def test_none_contract_type_returns_zero(self):
        """None contract_type -> value 0 (not silently treated as fixed)."""
        c = _contract(contract_type=None, budget_max=5000.0)
        assert estimate_contract_value(c) == pytest.approx(0.0)


# ── ROI scoring ──────────────────────────────────────────────────────────────


class TestROIScore:
    def test_known_inputs(self):
        """Verify ROI formula with hand-calculated values."""
        contract = _contract(
            budget_max=5000.0,
            contract_type=ContractType.fixed,
            proposals_count=10,
            client_hire_rate=0.80,
            connects_cost=16,
        )
        avail = _availability(hourly_value=100.0)
        match_score = 0.8

        result = calculate_roi_score(match_score, contract, avail)

        # contract_value = 5000
        assert result.contract_value == pytest.approx(5000.0)
        # connects_cost = 16 * 0.15 = 2.4
        assert result.connects_cost == pytest.approx(2.4)
        # time_cost = 0.25 * 100 = 25
        assert result.time_cost == pytest.approx(25.0)

        # win_prob = 0.8 * 0.80 * (1/log2(12))
        expected_wp = 0.8 * 0.80 * (1.0 / math.log2(12))
        assert result.win_probability == pytest.approx(expected_wp)

        # roi = (0.8 * 5000 * win_prob) / (2.4 + 25.0)
        expected_roi = (0.8 * 5000.0 * expected_wp) / (2.4 + 25.0)
        assert result.roi_score == pytest.approx(expected_roi)

    def test_zero_budget(self):
        """Zero budget -> roi_score 0."""
        contract = _contract(budget_max=0.0)
        avail = _availability()
        result = calculate_roi_score(0.8, contract, avail)
        assert result.roi_score == pytest.approx(0.0)

    def test_zero_connects_and_zero_hourly_value(self):
        """Denominator = 0 -> roi_score = 0 (no division by zero)."""
        contract = _contract(connects_cost=0)
        avail = _availability(hourly_value=0.0)
        result = calculate_roi_score(0.8, contract, avail)
        assert result.roi_score == pytest.approx(0.0)

    def test_none_fields_handled(self):
        """Contracts with None fields don't crash."""
        contract = _contract(
            budget_max=None,
            proposals_count=None,
            client_hire_rate=None,
            connects_cost=None,
        )
        avail = _availability()
        result = calculate_roi_score(0.5, contract, avail)
        assert result.roi_score == pytest.approx(0.0)

    def test_hourly_contract_roi(self):
        """Hourly contract uses hourly_rate * 160 for value."""
        contract = _contract(
            budget_max=100.0,
            contract_type=ContractType.hourly,
            proposals_count=5,
            client_hire_rate=0.90,
            connects_cost=8,
        )
        avail = _availability(hourly_value=100.0)
        result = calculate_roi_score(0.9, contract, avail)

        assert result.contract_value == pytest.approx(100.0 * 160)
        assert result.roi_score > 0


# ── Percentile-based indicators ─────────────────────────────────────────────


class TestIndicators:
    def test_green_top_25(self):
        """Score above 75th percentile -> green."""
        scores = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        assert assign_indicator(10.0, scores) == "green"
        assert assign_indicator(9.0, scores) == "green"

    def test_red_bottom_25(self):
        """Score below 25th percentile -> red."""
        scores = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        assert assign_indicator(1.0, scores) == "red"

    def test_yellow_middle(self):
        """Score in the middle 50% -> yellow."""
        scores = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        assert assign_indicator(5.0, scores) == "yellow"

    def test_empty_scores_returns_red(self):
        """Empty score list -> red."""
        assert assign_indicator(5.0, []) == "red"

    def test_single_score(self):
        """Single score: it's both the min and max, so yellow (on boundary)."""
        result = assign_indicator(5.0, [5.0])
        assert result == "yellow"

    def test_all_same_scores(self):
        """All identical scores -> yellow for any matching score."""
        scores = [5.0, 5.0, 5.0, 5.0]
        assert assign_indicator(5.0, scores) == "yellow"

    def test_four_scores_boundary(self):
        """With exactly 4 values, check boundaries using statistics.quantiles.

        statistics.quantiles([1,2,3,4], n=4) -> [1.25, 2.5, 3.75]
        so p25=1.25, p75=3.75.
        """
        scores = [1.0, 2.0, 3.0, 4.0]
        assert assign_indicator(0.5, scores) == "red"   # below p25 (1.25)
        assert assign_indicator(1.0, scores) == "red"   # below p25 (1.25)
        assert assign_indicator(2.5, scores) == "yellow"
        assert assign_indicator(4.0, scores) == "green"  # above p75 (3.75)
        assert assign_indicator(5.0, scores) == "green"


# ── Availability filter ─────────────────────────────────────────────────────


class TestAvailabilityFilter:
    def test_passes_all_checks(self):
        """Contract that meets all criteria passes."""
        contract = _contract(
            contract_type=ContractType.fixed,
            budget_max=1000.0,
        )
        avail = _availability(
            preferred_contract_type=PreferredContractType.both,
            min_fixed_budget=500.0,
        )
        assert passes_availability_filter(contract, avail) is True

    def test_fails_hourly_rate_floor(self):
        """Hourly contract below min rate fails."""
        contract = _contract(
            contract_type=ContractType.hourly,
            budget_max=50.0,
        )
        avail = _availability(
            preferred_contract_type=PreferredContractType.both,
            min_hourly_rate=75.0,
        )
        assert passes_availability_filter(contract, avail) is False

    def test_passes_hourly_rate_floor(self):
        """Hourly contract at or above min rate passes."""
        contract = _contract(
            contract_type=ContractType.hourly,
            budget_max=75.0,
        )
        avail = _availability(
            preferred_contract_type=PreferredContractType.both,
            min_hourly_rate=75.0,
        )
        assert passes_availability_filter(contract, avail) is True

    def test_fails_fixed_budget_floor(self):
        """Fixed contract below min budget fails."""
        contract = _contract(
            contract_type=ContractType.fixed,
            budget_max=200.0,
        )
        avail = _availability(
            preferred_contract_type=PreferredContractType.both,
            min_fixed_budget=500.0,
        )
        assert passes_availability_filter(contract, avail) is False

    def test_fails_contract_type_mismatch(self):
        """Prefers hourly but contract is fixed -> fails."""
        contract = _contract(contract_type=ContractType.fixed, budget_max=5000.0)
        avail = _availability(
            preferred_contract_type=PreferredContractType.hourly,
        )
        assert passes_availability_filter(contract, avail) is False

    def test_both_preference_always_passes_type(self):
        """Preference 'both' never fails on contract type."""
        for ct in [ContractType.hourly, ContractType.fixed]:
            contract = _contract(contract_type=ct, budget_max=10000.0)
            avail = _availability(
                preferred_contract_type=PreferredContractType.both,
            )
            assert passes_availability_filter(contract, avail) is True

    def test_none_contract_type_passes_type_check(self):
        """If contract type is None, type check is skipped."""
        contract = _contract(contract_type=None, budget_max=10000.0)
        avail = _availability(
            preferred_contract_type=PreferredContractType.hourly,
        )
        assert passes_availability_filter(contract, avail) is True

    def test_none_budget_passes_rate_floor(self):
        """If budget is None, rate floor check is skipped."""
        contract = _contract(contract_type=ContractType.hourly, budget_max=None)
        avail = _availability(min_hourly_rate=75.0)
        assert passes_availability_filter(contract, avail) is True


# ── Auto-skip logic ─────────────────────────────────────────────────────────


class TestAutoSkip:
    """Tests for auto-skip logic."""

    def _contract_create(self, **overrides) -> ContractCreate:
        defaults = dict(
            platform="upwork",
            external_id="test-1",
            budget_max=5000.0,
            contract_type="fixed",
            proposals_count=10,
            client_hire_rate=0.8,
            client_total_spent=10000.0,
        )
        defaults.update(overrides)
        return ContractCreate(**defaults)

    def test_no_skip_high_probability(self):
        c = self._contract_create()
        reason = determine_skip_reason(0.5, 0.7, c, _availability())
        assert reason is None

    def test_skip_low_match(self):
        c = self._contract_create()
        reason = determine_skip_reason(0.10, 0.15, c, _availability())
        assert reason == "low_match"

    def test_skip_high_competition(self):
        c = self._contract_create(proposals_count=50)
        reason = determine_skip_reason(0.10, 0.30, c, _availability())
        assert reason == "high_competition"

    def test_skip_low_budget_hourly(self):
        c = self._contract_create(contract_type="hourly", budget_max=30.0)
        reason = determine_skip_reason(0.10, 0.30, c, _availability(min_hourly_rate=75.0))
        assert reason == "low_budget"

    def test_skip_low_client_quality(self):
        c = self._contract_create(client_hire_rate=0.10, client_total_spent=0)
        reason = determine_skip_reason(0.10, 0.30, c, _availability())
        assert reason == "low_client_quality"

    def test_priority_low_budget_over_low_match(self):
        """low_budget has highest priority."""
        c = self._contract_create(contract_type="hourly", budget_max=30.0)
        reason = determine_skip_reason(0.05, 0.10, c, _availability(min_hourly_rate=75.0))
        assert reason == "low_budget"
