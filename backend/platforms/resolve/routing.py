"""Persist a Resolution onto a job row and route engine-fillable jobs to the
working assisted-fill channel. The caller owns the commit."""
from __future__ import annotations

from backend.core.enums import SubmissionChannel
from backend.db.models import OpportunityDB
from backend.platforms.ats_registry import Capability
from backend.platforms.resolve.resolution import Resolution


def apply_resolution(job: OpportunityDB, res: Resolution) -> None:
    """Write the resolution columns; if engine-fillable, flip the job to the
    `browser` channel and point its URL at the real form. Does not commit."""
    job.resolved_url = res.resolved_url
    job.detected_ats = res.detected_ats
    job.ats_capability = res.capability
    job.resolution_status = res.status
    job.resolution_tier = res.tier
    if res.capability is Capability.engine_fillable and res.resolved_url:
        job.submission_channel = SubmissionChannel.browser
        job.url = res.resolved_url
