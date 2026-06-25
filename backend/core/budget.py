"""Pure budget affordability logic — no DB, no I/O, trivially testable.

A finalist is affordable only if adding it keeps every applicable cap satisfied:
the rolling connects cap, the rolling generation-app cap, and (if set) the
per-run app cap. 'Whichever is tighter wins' falls out of requiring ALL caps to
pass for each next item.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

EST_DOLLARS_PER_APP = 0.05  # display-only estimate of generation $ per application


@dataclass(frozen=True)
class BudgetCaps:
    connects_cap: int
    gen_apps_cap: int
    per_run_cap: int | None  # None = no per-run app limit
    dollars_cap: float = float("inf")  # rolling generation $/period; inf = unenforced
    est_dollars_per_app: float = EST_DOLLARS_PER_APP  # pre-call estimate for the gate


def week_start(now: datetime) -> datetime:
    """Monday 00:00 UTC of the week containing *now*."""
    aware = now if now.tzinfo else now.replace(tzinfo=UTC)
    aware = aware.astimezone(UTC)
    midnight = aware.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight - timedelta(days=aware.weekday())


def can_afford_next(
    *,
    connects_used: float,
    gen_apps_used: float,
    per_run_used: int,
    caps: BudgetCaps,
    next_connects: float,
    dollars_used: float = 0.0,
) -> bool:
    """True iff processing one more finalist keeps every applicable cap satisfied.

    The dollar check uses ``est_dollars_per_app`` because a generation's true cost
    is unknown until the call returns; the ledger records actuals afterward.
    """
    if connects_used + next_connects > caps.connects_cap:
        return False
    if gen_apps_used + 1 > caps.gen_apps_cap:
        return False
    if caps.per_run_cap is not None and per_run_used + 1 > caps.per_run_cap:
        return False
    if dollars_used + caps.est_dollars_per_app > caps.dollars_cap:
        return False
    return True
