"""Tests for the new opportunity enums."""

from backend.core.enums import OpportunityKind, SubmissionChannel


def test_opportunity_kind_values():
    assert OpportunityKind.contract.value == "contract"
    assert OpportunityKind.job.value == "job"


def test_submission_channel_values():
    assert SubmissionChannel.direct.value == "direct"
    assert SubmissionChannel.browser.value == "browser"
