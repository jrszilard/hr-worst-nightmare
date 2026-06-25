"""Resolve one job through the tiers in order. Tier 1 (data) is free; Tier 2
(headless) only runs when Tier 1 fails and headless is enabled. Tier 3 is the
interactive Chrome-MCP procedure (out of band, see docs/tier3-chrome-mcp-resolution.md)."""
from __future__ import annotations

from typing import Callable

from backend.platforms.resolve.data_tier import resolve_from_data
from backend.platforms.resolve.headless_tier import (
    PlaywrightResolverBrowser, ResolverBrowser, resolve_headless,
)
from backend.platforms.resolve.resolution import Resolution, ResolutionStatus


def _default_browser() -> ResolverBrowser:
    return PlaywrightResolverBrowser()


async def resolve_job(
    url: str | None,
    apply_options: list[dict] | None,
    *,
    headless: bool = True,
    make_browser: Callable[[], ResolverBrowser] | None = None,
) -> Resolution:
    """Tier 1 (data) then, if unresolved and headless is on, Tier 2 (headless)."""
    res = resolve_from_data(url, apply_options)
    if res.status is ResolutionStatus.resolved or not headless or not url:
        return res
    return await resolve_headless(url, make_browser or _default_browser)
