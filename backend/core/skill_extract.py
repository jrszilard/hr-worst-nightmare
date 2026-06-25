"""Deterministic skill extraction: find which vocabulary skills appear in free text.

Used by board discovery so postings without a structured skill list still score
through the existing match pipeline. No LLM — pure regex word-boundary matching.
"""

from __future__ import annotations

import re


def extract_skills(text: str | None, vocab: list[str]) -> list[str]:
    """Return vocab skills present in *text*, in vocabulary order, deduped."""
    if not text:
        return []
    found: list[str] = []
    for skill in vocab:
        # Word-boundary match; escape regex specials in skill (e.g. "C++").
        pattern = r"(?<![A-Za-z0-9])" + re.escape(skill) + r"(?![A-Za-z0-9])"
        if re.search(pattern, text, flags=re.IGNORECASE) and skill not in found:
            found.append(skill)
    return found
