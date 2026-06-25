"""Per-async-task token usage accumulator.

Wrap a generation in ``with collect_usage() as acc:`` and call ``record_usage``
after each Claude ``messages.create``. ``acc.cost_usd()`` gives the total dollar
cost via the pricing map. Outside a ``collect_usage`` block, ``record_usage`` is
a no-op (so generation works in contexts that don't meter).
"""

from __future__ import annotations

import contextlib
import contextvars
from dataclasses import dataclass, field
from typing import Any, Iterator

from backend.core.pricing import cost_usd

_current: contextvars.ContextVar = contextvars.ContextVar("usage_accumulator", default=None)


@dataclass
class UsageAccumulator:
    # Each entry is (model, input_tokens, output_tokens).
    entries: list[tuple[str, int, int]] = field(default_factory=list)

    def add(self, model: str, input_tokens: int, output_tokens: int) -> None:
        self.entries.append((model, int(input_tokens or 0), int(output_tokens or 0)))

    @property
    def input_tokens(self) -> int:
        return sum(e[1] for e in self.entries)

    @property
    def output_tokens(self) -> int:
        return sum(e[2] for e in self.entries)

    def cost_usd(self) -> float:
        return round(sum(cost_usd(m, i, o) for (m, i, o) in self.entries), 6)


@contextlib.contextmanager
def collect_usage() -> Iterator[UsageAccumulator]:
    acc = UsageAccumulator()
    token = _current.set(acc)
    try:
        yield acc
    finally:
        _current.reset(token)


def record_usage(model: str, response: Any) -> None:
    acc = _current.get()
    if acc is None:
        return
    usage = getattr(response, "usage", None)
    if usage is None:
        return
    acc.add(model, getattr(usage, "input_tokens", 0), getattr(usage, "output_tokens", 0))
