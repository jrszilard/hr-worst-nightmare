from types import SimpleNamespace

import pytest

from backend.ai.usage import collect_usage, record_usage


def _fake_response(input_tokens: int, output_tokens: int):
    return SimpleNamespace(usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens))


def test_accumulates_tokens_within_context():
    with collect_usage() as acc:
        record_usage("claude-sonnet-4-6", _fake_response(100, 50))
        record_usage("claude-sonnet-4-6", _fake_response(20, 10))
    assert acc.input_tokens == 120
    assert acc.output_tokens == 60


def test_cost_uses_pricing():
    with collect_usage() as acc:
        record_usage("claude-sonnet-4-6", _fake_response(1_000_000, 0))
    assert acc.cost_usd() == 3.0


def test_record_outside_context_is_noop():
    # Must not raise when no accumulator is active.
    record_usage("claude-sonnet-4-6", _fake_response(100, 50))


def test_response_without_usage_is_ignored():
    with collect_usage() as acc:
        record_usage("claude-sonnet-4-6", SimpleNamespace(usage=None))
    assert acc.input_tokens == 0


@pytest.mark.asyncio
async def test_works_across_awaits():
    async def inner():
        record_usage("claude-sonnet-4-6", _fake_response(5, 5))

    with collect_usage() as acc:
        await inner()
        await inner()
    assert acc.input_tokens == 10
