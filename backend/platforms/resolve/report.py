"""Pure distribution report over a batch of Resolutions — the SP1 deliverable that
quantifies the SP2 opportunity (how much of the external lane is Workday vs iCIMS
vs already-engine-fillable vs needs a human)."""
from __future__ import annotations

from collections import Counter

from backend.platforms.resolve.resolution import Resolution


def distribution_report(resolutions: list[Resolution]) -> str:
    total = len(resolutions)
    by_cap_ats: Counter[tuple[str, str]] = Counter(
        (r.capability.value, r.detected_ats) for r in resolutions
    )
    by_status: Counter[str] = Counter(r.status.value for r in resolutions)
    lines = [f"Resolved {total} external job(s)", "", "By capability / ATS:"]
    for (cap, ats), n in sorted(by_cap_ats.items()):
        lines.append(f"  {cap:<16} {ats:<16} {n}")
    lines += ["", "By status:"]
    for status, n in sorted(by_status.items()):
        lines.append(f"  {status:<16} {n}")
    tier3 = by_status.get("blocked", 0) + by_status.get("needs_human", 0)
    lines += ["", f"Tier-3 candidates (blocked/needs_human): {tier3}"]
    return "\n".join(lines)
