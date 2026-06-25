"""Scan untrusted posting / form text for prompt-injection and AI-detection traps.

This module ONLY flags. It never obeys instructions found in the text. The
application generator treats all posting content as untrusted data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SNIPPET_PAD = 40


@dataclass
class TrapFlag:
    """A detected trap in untrusted text."""

    category: str   # instruction_override | identity_probe | hidden_directive
    pattern: str    # the matched text
    snippet: str    # surrounding context
    severity: str   # high | medium


# (category, severity, compiled regex)
_PATTERNS: list[tuple[str, str, re.Pattern]] = [
    ("instruction_override", "high", re.compile(
        r"(ignore|disregard|forget)\s+(all\s+|the\s+|any\s+)?(previous|prior|above)\s+instructions?",
        re.IGNORECASE)),
    ("instruction_override", "high", re.compile(
        r"\bnew instructions?\b\s*:", re.IGNORECASE)),
    ("identity_probe", "high", re.compile(
        r"are\s+you\s+(an?\s+)?(ai|a\s+bot|a\s+language\s+model|an?\s+llm|a\s+human|a\s+real\s+person)",
        re.IGNORECASE)),
    ("identity_probe", "high", re.compile(
        r"\bas an? (ai|language model|llm)\b", re.IGNORECASE)),
    ("identity_probe", "high", re.compile(
        r"if you\s+(are|'re)\s+an?\s+(ai|language model|bot)", re.IGNORECASE)),
    ("hidden_directive", "medium", re.compile(
        r"to prove (you are|you're) (human|not a bot)", re.IGNORECASE)),
    ("hidden_directive", "medium", re.compile(
        r"begin your (response|answer|application) with", re.IGNORECASE)),
    ("hidden_directive", "medium", re.compile(
        r"(respond|reply|answer) with the (word|phrase|exact|secret)", re.IGNORECASE)),
    ("hidden_directive", "medium", re.compile(
        r"include the (word|phrase|secret|code)\b", re.IGNORECASE)),
]


def _snippet(text: str, start: int, end: int) -> str:
    lo = max(0, start - _SNIPPET_PAD)
    hi = min(len(text), end + _SNIPPET_PAD)
    return text[lo:hi].strip()


def scan_for_traps(text: str) -> list[TrapFlag]:
    """Return a list of detected traps. Empty list means clean. Never raises."""
    if not text:
        return []
    flags: list[TrapFlag] = []
    for category, severity, pattern in _PATTERNS:
        for m in pattern.finditer(text):
            flags.append(TrapFlag(
                category=category,
                pattern=m.group(0),
                snippet=_snippet(text, m.start(), m.end()),
                severity=severity,
            ))
    return flags
