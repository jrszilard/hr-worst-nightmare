"""Pure Workday apply-URL resolution. No I/O, no browser.

Two host families are both live and in use:
  - <tenant>.wd<N>.myworkdayjobs.com/...            (tenant in the SUBDOMAIN)
  - wd<N>.myworkdaysite.com/recruiting/<tenant>/... (tenant in the PATH)
Never hardcode the data-center cell (wd1/wd3/wd5/wd103/...); keep req -1/-2 suffixes.
JSearch's is_direct flags are unreliable — the host is the only ground truth.
"""

from __future__ import annotations

from backend.platforms.ats_registry import classify


def is_workday_host(url: str | None) -> bool:
    """True if *url*'s host belongs to either Workday host family.
    Delegates to the shared ATS registry (single source of truth for hosts)."""
    return classify(url)[0] == "workday"


def pick_apply_url(
    apply_options: list[dict] | None, job_apply_link: str | None
) -> tuple[str | None, str]:
    """Choose the best Workday apply URL.

    Order: a Workday-host apply_options link > a Workday-host job_apply_link >
    (None, "resolve-in-session"). Returns (url_or_None, source_label).
    """
    for opt in apply_options or []:
        link = opt.get("apply_link")
        if is_workday_host(link):
            return link, "apply_options-host-match"
    if is_workday_host(job_apply_link):
        return job_apply_link, "job_apply_link"
    return None, "resolve-in-session"


def to_apply_route(url: str, *, manual: bool = False) -> str:
    """Return the deep-linkable apply route for a Workday job description URL.

    Appends /apply/autofillWithResume (or /apply/applyManually). If *url* is already
    an apply route ("/apply/" present), it is returned unchanged.
    """
    if "/apply/" in url:
        return url
    leaf = "applyManually" if manual else "autofillWithResume"
    return url.rstrip("/") + f"/apply/{leaf}"
