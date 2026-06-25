from backend.core.pricing import cost_usd


def test_sonnet_cost_known_rate():
    # 1M input @ $3, 1M output @ $15
    assert cost_usd("claude-sonnet-4-6", 1_000_000, 1_000_000) == 18.0


def test_partial_tokens():
    # 10k input + 2k output on sonnet
    cost = cost_usd("claude-sonnet-4-6", 10_000, 2_000)
    assert round(cost, 6) == round(0.01 * 3.0 + 0.002 * 15.0, 6)


def test_unknown_model_uses_default():
    assert cost_usd("some-future-model", 1_000_000, 0) == cost_usd("claude-sonnet-4-6", 1_000_000, 0)


def test_zero_tokens():
    assert cost_usd("claude-sonnet-4-6", 0, 0) == 0.0
