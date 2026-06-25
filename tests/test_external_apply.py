from backend.platforms.external_apply import open_posting_for_review
import inspect


def test_open_posting_is_async_and_takes_url():
    sig = inspect.signature(open_posting_for_review)
    assert "url" in sig.parameters
    assert inspect.iscoroutinefunction(open_posting_for_review)
