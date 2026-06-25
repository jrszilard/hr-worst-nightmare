"""Token -> dollar conversion. Pure, no I/O.

Rates are USD per 1M tokens (input, output). Confirm against current Anthropic
pricing when prices change; this is the single place to edit.
"""

from __future__ import annotations

# (input $/Mtok, output $/Mtok)
_PRICES: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-opus-4-7": (15.00, 75.00),
    "claude-haiku-4-5-20251001": (1.00, 5.00),
}
_DEFAULT: tuple[float, float] = (3.00, 15.00)


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Dollar cost of a single Claude call given its token counts."""
    in_rate, out_rate = _PRICES.get(model, _DEFAULT)
    return (input_tokens / 1_000_000) * in_rate + (output_tokens / 1_000_000) * out_rate
