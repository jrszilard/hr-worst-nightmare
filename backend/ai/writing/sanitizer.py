"""Deterministic, total text sanitizer.

Guarantees forbidden punctuation is gone regardless of what the LLM produced,
and reports cliché phrases (without deleting prose). Pure and never raises.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from backend.ai.writing.style import BANNED_CLICHES, SMART_QUOTE_MAP

# Dash characters that should become a comma when used as an aside separator.
_DASH_RE = re.compile(r"\s*[—–]\s*")
# Arrow characters -> the word "to".
_ARROW_RE = re.compile(r"\s*[→➔➜⇒]\s*")
# " + " used as a conjunction -> " and ".
_PLUS_CONJ_RE = re.compile(r"\s+\+\s+")
# Collapse any accidental doubled spaces/commas produced by replacement.
_DOUBLE_SPACE_RE = re.compile(r" {2,}")
_DOUBLE_COMMA_RE = re.compile(r",\s*,")


@dataclass
class SanitizerReport:
    """What the sanitizer changed and flagged."""

    punctuation_fixes: list[str] = field(default_factory=list)
    cliches_found: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.punctuation_fixes)


def sanitize(text: str) -> tuple[str, SanitizerReport]:
    """Return (clean_text, report). Total: handles empty/garbage input."""
    report = SanitizerReport()
    if not text:
        return "", report

    out = text

    if _DASH_RE.search(out):
        out = _DASH_RE.sub(", ", out)
        report.punctuation_fixes.append("replaced em/en dash with comma")
    if _ARROW_RE.search(out):
        out = _ARROW_RE.sub(" to ", out)
        report.punctuation_fixes.append("replaced arrow with 'to'")
    if _PLUS_CONJ_RE.search(out):
        out = _PLUS_CONJ_RE.sub(" and ", out)
        report.punctuation_fixes.append("replaced '+' conjunction with 'and'")

    for smart, ascii_ in SMART_QUOTE_MAP.items():
        if smart in out:
            out = out.replace(smart, ascii_)
            report.punctuation_fixes.append(f"normalised {smart!r} to {ascii_!r}")

    # Tidy artefacts from replacements.
    out = _DOUBLE_COMMA_RE.sub(",", out)
    out = _DOUBLE_SPACE_RE.sub(" ", out)

    lowered = out.lower()
    for cliche in BANNED_CLICHES:
        if cliche in lowered:
            report.cliches_found.append(cliche)

    return out, report
