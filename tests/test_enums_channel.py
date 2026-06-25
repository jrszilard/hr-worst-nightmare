from backend.core.enums import SubmissionChannel


def test_external_channel_exists():
    assert SubmissionChannel("external") is SubmissionChannel.external
    assert SubmissionChannel.external.value == "external"
