from backend.platforms.ats_registry import Capability
from backend.platforms.resolve.report import distribution_report
from backend.platforms.resolve.resolution import Resolution, ResolutionStatus, ResolutionTier


def _r(ats, cap, status, tier=ResolutionTier.headless, url="https://x"):
    return Resolution(url, ats, cap, status, tier)


def test_distribution_report_counts_and_tier3_total():
    rows = [
        _r("greenhouse", Capability.engine_fillable, ResolutionStatus.resolved),
        _r("greenhouse", Capability.engine_fillable, ResolutionStatus.resolved),
        _r("workday", Capability.multi_page, ResolutionStatus.resolved),
        _r("unknown", Capability.manual, ResolutionStatus.blocked),
        _r("unknown", Capability.manual, ResolutionStatus.dead),
    ]
    out = distribution_report(rows)
    assert "Resolved 5 external job(s)" in out
    assert "engine_fillable" in out and "greenhouse" in out
    assert "multi_page" in out and "workday" in out
    # 2 greenhouse engine_fillable on one line
    assert any(line.strip().endswith("2") and "greenhouse" in line for line in out.splitlines())
    assert "Tier-3 candidates (blocked/needs_human): 1" in out


def test_distribution_report_empty():
    out = distribution_report([])
    assert "Resolved 0 external job(s)" in out
