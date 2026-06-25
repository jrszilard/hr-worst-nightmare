"""Tests for job ranking (backend.core.scoring.calculate_job_priority).

Jobs are ranked by fit, not connects-ROI. See the design decision in the
opportunity-model spec: full-time / contract jobs are not a connects-spend
problem, so a dollar ROI would be mostly noise.
"""

from backend.core.scoring import calculate_job_priority


def test_uses_match_alone_when_no_description_fit():
    assert calculate_job_priority(0.8) == 0.8


def test_blends_match_and_description_fit():
    # 0.5 * 0.6 + 0.5 * 1.0 = 0.8
    assert calculate_job_priority(0.6, description_fit=1.0) == 0.8


def test_clamps_to_unit_interval():
    assert calculate_job_priority(2.0, description_fit=2.0) == 1.0
    assert calculate_job_priority(-1.0) == 0.0


def test_strong_fit_outranks_weak_fit():
    strong = calculate_job_priority(0.9, description_fit=0.9)
    weak = calculate_job_priority(0.2, description_fit=0.1)
    assert strong > weak
