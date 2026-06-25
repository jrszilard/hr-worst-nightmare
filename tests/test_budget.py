"""Unit tests for the pure budget logic."""

from datetime import UTC, datetime

from backend.core.budget import BudgetCaps, EST_DOLLARS_PER_APP, can_afford_next, week_start


def test_week_start_is_monday_midnight_utc():
    # 2026-05-22 is a Friday.
    ws = week_start(datetime(2026, 5, 22, 15, 30, tzinfo=UTC))
    assert ws == datetime(2026, 5, 18, 0, 0, tzinfo=UTC)  # Monday


def test_can_afford_next_within_all_caps():
    caps = BudgetCaps(connects_cap=60, gen_apps_cap=20, per_run_cap=5)
    assert can_afford_next(connects_used=40, gen_apps_used=10, per_run_used=2,
                           caps=caps, next_connects=10) is True


def test_connects_cap_blocks():
    caps = BudgetCaps(connects_cap=60, gen_apps_cap=20, per_run_cap=5)
    assert can_afford_next(connects_used=55, gen_apps_used=0, per_run_used=0,
                           caps=caps, next_connects=10) is False


def test_generation_app_cap_blocks():
    caps = BudgetCaps(connects_cap=60, gen_apps_cap=20, per_run_cap=None)
    assert can_afford_next(connects_used=0, gen_apps_used=20, per_run_used=0,
                           caps=caps, next_connects=0) is False


def test_per_run_cap_is_tighter_and_blocks():
    caps = BudgetCaps(connects_cap=999, gen_apps_cap=999, per_run_cap=3)
    assert can_afford_next(connects_used=0, gen_apps_used=0, per_run_used=3,
                           caps=caps, next_connects=0) is False


def test_per_run_cap_none_means_no_run_limit():
    caps = BudgetCaps(connects_cap=999, gen_apps_cap=999, per_run_cap=None)
    assert can_afford_next(connects_used=0, gen_apps_used=0, per_run_used=100,
                           caps=caps, next_connects=0) is True


def test_est_dollars_constant_positive():
    assert EST_DOLLARS_PER_APP > 0
