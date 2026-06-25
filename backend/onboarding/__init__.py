"""Onboarding orchestrator: ingest -> extract -> write draft bundle."""

from __future__ import annotations

import anthropic

from backend.core.profile_context import ProfileContext
from backend.onboarding.extractor import extract_profile
from backend.onboarding.ingest import gather_inputs
from backend.onboarding.report import write_outputs


async def run_onboarding(
    ctx: ProfileContext, *, client: anthropic.AsyncAnthropic | None = None
) -> None:
    """Read ctx.inputs_dir, extract a profile draft, write the bundle + report."""
    ingest = gather_inputs(ctx)
    extraction = await extract_profile(ingest, client=client)
    write_outputs(ctx, extraction, ingest)
