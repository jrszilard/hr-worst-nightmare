"""Single source of truth for ATS detection: classify an apply URL into an ATS
slug + a capability that drives routing. Pure (no I/O)."""
from __future__ import annotations

import enum
from urllib.parse import urlparse


class Capability(str, enum.Enum):
    engine_fillable = "engine_fillable"  # single-page hosted forms the BrowserEngine can drive
    multi_page = "multi_page"            # known ATS not engine-validated yet: Workday/iCIMS wizards AND single-page ATSs (e.g. Workable) the engine hasn't been proven on -> routed manual until SP2
    aggregator = "aggregator"            # job boards that relist; not a real apply form
    manual = "manual"                    # careers portals / unknown


# host suffix -> (ats slug, capability). Longest-suffix match wins.
_REGISTRY: dict[str, tuple[str, Capability]] = {
    "greenhouse.io": ("greenhouse", Capability.engine_fillable),
    "lever.co": ("lever", Capability.engine_fillable),
    "ashbyhq.com": ("ashby", Capability.engine_fillable),
    "myworkdayjobs.com": ("workday", Capability.multi_page),
    "myworkdaysite.com": ("workday", Capability.multi_page),
    "icims.com": ("icims", Capability.multi_page),
    "smartrecruiters.com": ("smartrecruiters", Capability.multi_page),
    "successfactors.com": ("successfactors", Capability.multi_page),
    "taleo.net": ("taleo", Capability.multi_page),
    "workable.com": ("workable", Capability.multi_page),
    "jobvite.com": ("jobvite", Capability.multi_page),
    "linkedin.com": ("linkedin", Capability.aggregator),
    "indeed.com": ("indeed", Capability.aggregator),
    "glassdoor.com": ("glassdoor", Capability.aggregator),
    "ziprecruiter.com": ("ziprecruiter", Capability.aggregator),
    "monster.com": ("monster", Capability.aggregator),
    "talent.com": ("talent", Capability.aggregator),
    "bebee.com": ("bebee", Capability.aggregator),
    "dice.com": ("dice", Capability.aggregator),
    "lensa.com": ("lensa", Capability.aggregator),
    "adzuna.com": ("adzuna", Capability.aggregator),
    "simplyhired.com": ("simplyhired", Capability.aggregator),
}


def _host(url: str | None) -> str:
    return (urlparse(url or "").hostname or "").lower()


def classify(url: str | None) -> tuple[str, Capability]:
    """Return (ats_slug, capability) for an apply URL. Unknown -> ('unknown', manual)."""
    host = _host(url)
    best_suffix: str | None = None
    best_val: tuple[str, Capability] | None = None
    for suffix, val in _REGISTRY.items():
        if host == suffix or host.endswith("." + suffix):
            if best_suffix is None or len(suffix) > len(best_suffix):
                best_suffix, best_val = suffix, val
    if best_val is not None:
        return best_val
    return ("unknown", Capability.manual)


def is_engine_fillable(url: str | None) -> bool:
    return classify(url)[1] is Capability.engine_fillable


def first_known_ats(urls: list[str | None]) -> tuple[str, str, Capability] | None:
    """First engine_fillable URL among *urls*, else the first multi_page URL, else None.

    Aggregator / unknown URLs never count. Returns (url, ats_slug, capability).
    Shared by the data tier (Tier 1) and the headless tier (Tier 2)."""
    fallback: tuple[str, str, Capability] | None = None
    for url in urls:
        if not url:
            continue
        slug, cap = classify(url)
        if cap is Capability.engine_fillable:
            return (url, slug, cap)
        if cap is Capability.multi_page and fallback is None:
            fallback = (url, slug, cap)
    return fallback
