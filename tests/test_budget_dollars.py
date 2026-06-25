from backend.core.enums import SpendKind


def test_generation_dollars_spend_kind_exists():
    assert SpendKind.generation_dollars.value == "generation_dollars"


from backend.core.budget import BudgetCaps, can_afford_next


def _caps(**kw):
    base = dict(connects_cap=1000, gen_apps_cap=1000, per_run_cap=None,
                dollars_cap=1.0, est_dollars_per_app=0.05)
    base.update(kw)
    return BudgetCaps(**base)


def test_dollars_cap_blocks_when_estimate_exceeds():
    caps = _caps(dollars_cap=0.10, est_dollars_per_app=0.05)
    # 0.05 used + 0.05 next = 0.10, ok; 0.10 used + 0.05 = 0.15 > 0.10, blocked
    assert can_afford_next(connects_used=0, gen_apps_used=0, per_run_used=0,
                           caps=caps, next_connects=0, dollars_used=0.05) is True
    assert can_afford_next(connects_used=0, gen_apps_used=0, per_run_used=0,
                           caps=caps, next_connects=0, dollars_used=0.10) is False


def test_dollars_default_infinite_does_not_block():
    caps = BudgetCaps(connects_cap=1000, gen_apps_cap=1000, per_run_cap=None)
    assert can_afford_next(connects_used=0, gen_apps_used=0, per_run_used=0,
                           caps=caps, next_connects=0) is True
