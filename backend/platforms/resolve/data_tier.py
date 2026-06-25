"""Tier 1 resolution: classify a job from its URL + persisted apply_options, no browser."""
from __future__ import annotations

from backend.platforms.ats_registry import Capability, first_known_ats
from backend.platforms.resolve.resolution import Resolution, ResolutionStatus, ResolutionTier


def resolve_from_data(url: str | None, apply_options: list[dict] | None) -> Resolution:
    """Resolve to a real ATS from data alone. Prefer engine_fillable, then multi_page.
    Aggregator/unknown links do not count as resolved (they need the browser tier)."""
    candidates: list[str | None] = [url]
    candidates.extend(opt.get("apply_link") for opt in (apply_options or []))
    hit = first_known_ats(candidates)
    if hit is not None:
        link, slug, cap = hit
        return Resolution(link, slug, cap, ResolutionStatus.resolved, ResolutionTier.data)
    return Resolution(None, "unknown", Capability.manual, ResolutionStatus.unresolved, ResolutionTier.data)
