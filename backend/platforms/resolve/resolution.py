"""Value object for an external-job apply resolution."""
from __future__ import annotations

import enum
from dataclasses import dataclass

from backend.platforms.ats_registry import Capability


class ResolutionStatus(str, enum.Enum):
    resolved = "resolved"
    blocked = "blocked"          # browser tier hit a login-wall / bot-block / timeout
    dead = "dead"               # posting no longer exists
    needs_human = "needs_human"  # flagged for the interactive Tier-3 procedure
    unresolved = "unresolved"    # no tier has resolved it yet


class ResolutionTier(str, enum.Enum):
    data = "data"            # Tier 1: classified from stored url + apply_options, no browser
    headless = "headless"    # Tier 2: headless Playwright click-through
    real_brave = "real_brave"  # Tier 3: interactive Chrome MCP + screenshots


@dataclass(frozen=True)
class Resolution:
    resolved_url: str | None
    detected_ats: str
    capability: Capability
    status: ResolutionStatus
    tier: ResolutionTier
